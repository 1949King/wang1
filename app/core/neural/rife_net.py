"""RIFE v4.9 神经补帧网络架构（vendor · MIT 许可）。

署名与许可（2026-11-20 T0 许可核查放行）
========================================
本文件 vendor 自以下两个 MIT 许可仓库的 RIFE v4.x（IFNet_m）架构，
用于加载官方发布的 ``rife49.pth``（v4.9）权重做视频插帧：

  - Megvii Research, ECCV2022-RIFE
    https://github.com/hzwer/ECCV2022-RIFE  （model/IFNet_m.py · model/refine.py · model/warplayer.py）
  - hzwer, Practical-RIFE
    https://github.com/hzwer/Practical-RIFE  （inference_video.py 推理管线）

两仓库 LICENSE 均为 MIT（Copyright (c) 2021 Zhewei Huang / Megvii）。
权重 rife49.pth 由作者以同一 MIT 许可发布（见 README 模型下载段）。
依 MIT 条款保留本署名与许可声明；架构代码按原样 vendor，仅做最小适配
（自包含 warp、去除训练专用分支依赖、增加加载期 key 集合校验）。

诚实纪律
========
- 本模块**只定义网络架构与推理前向**，绝不下载任何权重；
  权重由用户自行放置（见 rife_engine.RIFE_MODEL_GUIDANCE）。
- 加载时校验 checkpoint 的 key 集合与架构是否一致，不匹配抛
  RifeArchitectureError（上层据此诚实降级，绝不静默产出错误画面）。
- 推理输出为 RGB uint8 中间帧；非神经网络降级路径在 video_interpolate_job。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger("AI短剧编辑器.rife_net")


class RifeError(Exception):
    """RIFE 相关错误基类（供上层类型化降级）。"""


class RifeArchitectureError(RifeError):
    """checkpoint key 集合与架构不匹配（权重版本不符 / 文件损坏）。"""


class RifeUnavailableError(RifeError):
    """torch 不可用或模型缺失等环境性不可用。"""


class RifeOOMError(RifeError):
    """显存不足（CUDA OOM），上层据此降级光流。"""


# ── warp（vendor 自 Practical-RIFE model/warplayer.py，MIT）──────────────
_BACKWARP_TEN_GRID: Dict[Tuple[str, str], torch.Tensor] = {}


def warp(ten_input: torch.Tensor, ten_flow: torch.Tensor) -> torch.Tensor:
    """按光流反向采样（grid_sample），与上游 warplayer.warp 逐字一致。"""
    flow_device = ten_flow.device
    k = (str(flow_device), str(ten_flow.size()))
    if k not in _BACKWARP_TEN_GRID:
        ten_horizontal = torch.linspace(-1.0, 1.0, ten_flow.shape[3], device=flow_device).view(
            1, 1, 1, ten_flow.shape[3]).expand(ten_flow.shape[0], -1, ten_flow.shape[2], -1)
        ten_vertical = torch.linspace(-1.0, 1.0, ten_flow.shape[2], device=flow_device).view(
            1, 1, 1, ten_flow.shape[2], 1).expand(ten_flow.shape[0], -1, -1, ten_flow.shape[3])
        _BACKWARP_TEN_GRID[k] = torch.cat([ten_horizontal, ten_vertical], 1).to(flow_device)
    ten_flow = torch.cat([
        ten_flow[:, 0:1, :, :] / ((ten_input.shape[3] - 1.0) / 2.0),
        ten_flow[:, 1:2, :, :] / ((ten_input.shape[2] - 1.0) / 2.0),
    ], 1)
    g = (_BACKWARP_TEN_GRID[k] + ten_flow).permute(0, 2, 3, 1)
    return F.grid_sample(input=ten_input, grid=g, mode="bilinear",
                         padding_mode="border", align_corners=True)


def _conv(in_planes: int, out_planes: int, kernel_size: int = 3, stride: int = 1,
          padding: int = 1, dilation: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_planes, out_planes, kernel_size=kernel_size, stride=stride,
                  padding=padding, dilation=dilation, bias=True),
        nn.PReLU(out_planes),
    )


def _deconv(in_planes: int, out_planes: int) -> nn.Sequential:
    return nn.Sequential(
        nn.ConvTranspose2d(in_channels=in_planes, out_channels=out_planes,
                           kernel_size=4, stride=2, padding=1, bias=True),
        nn.PReLU(out_planes),
    )


class Conv2(nn.Module):
    """两层卷积块（vendor 自 refine.py）。"""

    def __init__(self, in_planes: int, out_planes: int, stride: int = 2):
        super().__init__()
        self.conv1 = _conv(in_planes, out_planes, 3, stride, 1)
        self.conv2 = _conv(out_planes, out_planes, 3, 1, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv2(self.conv1(x))


_C = 16


class Contextnet(nn.Module):
    """上下文特征金字塔（vendor 自 refine.py，c=16）。"""

    def __init__(self):
        super().__init__()
        self.conv1 = Conv2(3, _C)
        self.conv2 = Conv2(_C, 2 * _C)
        self.conv3 = Conv2(2 * _C, 4 * _C)
        self.conv4 = Conv2(4 * _C, 8 * _C)

    def forward(self, x: torch.Tensor, flow: torch.Tensor) -> List[torch.Tensor]:
        x = self.conv1(x)
        flow = F.interpolate(flow, scale_factor=0.5, mode="bilinear",
                             align_corners=False, recompute_scale_factor=False) * 0.5
        f1 = warp(x, flow)
        x = self.conv2(x)
        flow = F.interpolate(flow, scale_factor=0.5, mode="bilinear",
                             align_corners=False, recompute_scale_factor=False) * 0.5
        f2 = warp(x, flow)
        x = self.conv3(x)
        flow = F.interpolate(flow, scale_factor=0.5, mode="bilinear",
                             align_corners=False, recompute_scale_factor=False) * 0.5
        f3 = warp(x, flow)
        x = self.conv4(x)
        flow = F.interpolate(flow, scale_factor=0.5, mode="bilinear",
                             align_corners=False, recompute_scale_factor=False) * 0.5
        f4 = warp(x, flow)
        return [f1, f2, f3, f4]


class Unet(nn.Module):
    """残差 refine U-Net（vendor 自 refine.py，c=16）。"""

    def __init__(self):
        super().__init__()
        self.down0 = Conv2(17, 2 * _C)
        self.down1 = Conv2(4 * _C, 4 * _C)
        self.down2 = Conv2(8 * _C, 8 * _C)
        self.down3 = Conv2(16 * _C, 16 * _C)
        self.up0 = _deconv(32 * _C, 8 * _C)
        self.up1 = _deconv(16 * _C, 4 * _C)
        self.up2 = _deconv(8 * _C, 2 * _C)
        self.up3 = _deconv(4 * _C, _C)
        self.conv = nn.Conv2d(_C, 3, 3, 1, 1)

    def forward(self, img0, img1, warped_img0, warped_img1, mask, flow, c0, c1):
        s0 = self.down0(torch.cat((img0, img1, warped_img0, warped_img1, mask, flow), 1))
        s1 = self.down1(torch.cat((s0, c0[0], c1[0]), 1))
        s2 = self.down2(torch.cat((s1, c0[1], c1[1]), 1))
        s3 = self.down3(torch.cat((s2, c0[2], c1[2]), 1))
        x = self.up0(torch.cat((s3, c0[3], c1[3]), 1))
        x = self.up1(torch.cat((x, s2), 1))
        x = self.up2(torch.cat((x, s1), 1))
        x = self.up3(torch.cat((x, s0), 1))
        return torch.sigmoid(self.conv(x))


class IFBlock(nn.Module):
    """多尺度光流估计块（vendor 自 IFNet_m.py）。"""

    def __init__(self, in_planes: int, c: int = 64):
        super().__init__()
        self.conv0 = nn.Sequential(
            _conv(in_planes, c // 2, 3, 2, 1),
            _conv(c // 2, c, 3, 2, 1),
        )
        self.convblock = nn.Sequential(*[_conv(c, c) for _ in range(8)])
        self.lastconv = nn.ConvTranspose2d(c, 5, 4, 2, 1)

    def forward(self, x: torch.Tensor, flow, scale: float):
        if scale != 1:
            x = F.interpolate(x, scale_factor=1.0 / scale, mode="bilinear", align_corners=False)
        if flow is not None:
            flow = F.interpolate(flow, scale_factor=1.0 / scale, mode="bilinear",
                                 align_corners=False) * 1.0 / scale
            x = torch.cat((x, flow), 1)
        x = self.conv0(x)
        x = self.convblock(x) + x
        tmp = self.lastconv(x)
        tmp = F.interpolate(tmp, scale_factor=scale * 2, mode="bilinear", align_corners=False)
        flow = tmp[:, :4] * scale * 2
        mask = tmp[:, 4:5]
        return flow, mask


class IFNet_m(nn.Module):
    """RIFE v4.x 主网络（vendor 自 IFNet_m.py，匹配 rife49.pth v4.9）。"""

    def __init__(self):
        super().__init__()
        self.block0 = IFBlock(6 + 1, c=240)
        self.block1 = IFBlock(13 + 4 + 1, c=150)
        self.block2 = IFBlock(13 + 4 + 1, c=90)
        self.block_tea = IFBlock(16 + 4 + 1, c=90)
        self.contextnet = Contextnet()
        self.unet = Unet()

    def forward(self, x: torch.Tensor, scale=(4, 2, 1), timestep: float = 0.5,
                returnflow: bool = False):
        timestep = (x[:, :1].clone() * 0 + 1) * timestep
        img0 = x[:, :3]
        img1 = x[:, 3:6]
        # x[:, 6:] 为 gt（训练用）；推理时为空（0 通道），教师分支自动跳过，故不取用
        flow_list: List[torch.Tensor] = []
        merged: List = []
        mask_list: List[torch.Tensor] = []
        warped_img0 = img0
        warped_img1 = img1
        flow = None
        mask = None
        stu = [self.block0, self.block1, self.block2]
        for i in range(3):
            if flow is not None:
                flow_d, mask_d = stu[i](
                    torch.cat((img0, img1, timestep, warped_img0, warped_img1, mask), 1),
                    flow, scale=scale[i])
                flow = flow + flow_d
                mask = mask + mask_d
            else:
                flow, mask = stu[i](torch.cat((img0, img1, timestep), 1), None, scale=scale[i])
            mask_list.append(torch.sigmoid(mask))
            flow_list.append(flow)
            warped_img0 = warp(img0, flow[:, :2])
            warped_img1 = warp(img1, flow[:, 2:4])
            merged.append((warped_img0, warped_img1))
        # 推理（gt 空）跳过教师蒸馏分支；仅训练态使用 block_tea
        for i in range(3):
            merged[i] = merged[i][0] * mask_list[i] + merged[i][1] * (1 - mask_list[i])
        if returnflow:
            return flow
        c0 = self.contextnet(img0, flow[:, :2])
        c1 = self.contextnet(img1, flow[:, 2:4])
        tmp = self.unet(img0, img1, warped_img0, warped_img1, mask, flow, c0, c1)
        res = tmp[:, :3] * 2 - 1
        merged[2] = torch.clamp(merged[2] + res, 0, 1)
        return flow_list, mask_list[2], merged, None, None, 0


def load_flownet_state(flownet: IFNet_m, state_dict: Dict[str, torch.Tensor]) -> None:
    """校验 key 集合一致后加载权重；不匹配抛 RifeArchitectureError（诚实失败）。

    兼容 DataParallel 的 ``module.`` 前缀。要求 checkpoint 与架构 key 完全一致，
    避免版本不符时静默加载部分权重产出错误画面。
    """
    cleaned = {}
    for k, v in state_dict.items():
        cleaned[k[7:] if k.startswith("module.") else k] = v
    expected = set(flownet.state_dict().keys())
    got = set(cleaned.keys())
    if expected != got:
        missing = sorted(expected - got)[:6]
        extra = sorted(got - expected)[:6]
        raise RifeArchitectureError(
            f"RIFE 权重与 v4.9 架构不匹配（缺失 {len(expected - got)} / 多余 {len(got - expected)}）。"
            f"缺失示例={missing} 多余示例={extra}。请确认放置的是官方 rife49.pth（v4.9）。"
        )
    flownet.load_state_dict(cleaned, strict=True)


class Model:
    """RIFE v4.9 推理包装（镜像 Practical-RIFE train_log/RIFE_HDv3.py 的 Model）。"""

    def __init__(self):
        self.flownet = IFNet_m()
        self.version = 4.9

    def eval(self) -> "Model":
        self.flownet.eval()
        return self

    def to(self, device) -> "Model":
        self.flownet.to(device)
        return self

    @torch.no_grad()
    def inference(self, img0: torch.Tensor, img1: torch.Tensor,
                  timestep: float = 0.5, scale: float = 1.0) -> torch.Tensor:
        """img0/img1: (1,3,H,W) float[0,1]（已 pad）；返回中间帧 (1,3,H,W) float[0,1]。"""
        imgs = torch.cat((img0, img1), 1)
        scale_list = [4 * scale, 2 * scale, scale]
        _, _, merged, _, _, _ = self.flownet(imgs, scale_list, timestep)
        return merged[2]
