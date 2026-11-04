/**
 * localImage.ts — 本地图像模型列表与生成桥接。
 *
 * 后端已有 /host/local-image-generate（models/pull/generate），此前画布只在
 * App.tsx 调云端 generateImageViaHost，导致「本地模型已下载」无法进入生成面板。
 * 这里与 localVideo 保持同一边界：本地走 local-image-generate，云端仍走 bridge。
 */
import {
  BRIDGE,
  authHeaders,
  bridgeToken,
  generateImageViaHost,
  type ImageModelOption,
} from "./bridge";
import { LOCAL_CHANNEL_ID } from "./localVideo";
import { estimateImageSize } from "./imageSize";

export type LocalImageModel = {
  id: string;
  label: string;
  params?: string;
  modes?: string[];
  download_gb?: number;
  vram_gb?: number;
  ram_gb?: number;
  native_size?: number;
  note?: string;
  license?: string;
};

export type LocalImageModelList = {
  models: LocalImageModel[];
  downloaded: string[];
  available: boolean;
  unavailable_reason: string;
};

/** 读取本地图像模型清单；失败时返回空清单，不拖垮云端模型池。 */
export async function listLocalImageModels(): Promise<LocalImageModelList> {
  try {
    const res = await fetch(`${BRIDGE}/host/local-image-generate`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ action: "models", token: bridgeToken() }),
    });
    const data = await res.json();
    if (!data.ok) {
      return {
        models: [],
        downloaded: [],
        available: false,
        unavailable_reason: String(data.message || "本地图像模型接口未返回 ok"),
      };
    }
    const models: LocalImageModel[] = [];
    const seen = new Set<string>();
    const engines = data.engines || [];
    for (const engine of engines) {
      for (const model of engine.models || []) {
        if (!model?.id || seen.has(model.id)) continue;
        seen.add(model.id);
        models.push(model as LocalImageModel);
      }
    }
    return {
      models,
      downloaded: (data.downloaded || []) as string[],
      available: engines.some((engine: { available?: boolean }) => engine.available),
      unavailable_reason: String(data.unavailable_reason || ""),
    };
  } catch (e) {
    return {
      models: [],
      downloaded: [],
      available: false,
      unavailable_reason: `无法连接本地图像服务：${String(e)}`,
    };
  }
}

/** 本地模型与云模型共用同一组选项；本地条目明确标出下载和资源状态。 */
export function mergeLocalImageModels(
  cloud: ImageModelOption[] | undefined,
  local: { models?: LocalImageModel[]; downloaded?: string[] },
): ImageModelOption[] {
  const localOptions = (local.models || []).map((model) => {
    const downloaded = (local.downloaded || []).includes(model.id);
    const size = downloaded ? "已下载" : `需下载 ${model.download_gb || "?"}GB`;
    const resources = [model.vram_gb ? `${model.vram_gb}GB 显存` : "", model.ram_gb ? `${model.ram_gb}GB 内存` : ""]
      .filter(Boolean)
      .join(" / ");
    return {
      channel_id: LOCAL_CHANNEL_ID,
      channel_name: "本地",
      model: model.id,
      label: `本地 · ${model.label} · ${size}${resources ? ` · ${resources}` : ""}`,
    };
  });
  return [...(cloud || []), ...localOptions];
}

type ImageRequest = Omit<Parameters<typeof generateImageViaHost>[0], "model" | "channel_id">;

/** 本地图像生成请求；模型未下载时后端返回诚实错误，不在前端伪造成功。 */
export async function generateImageLocalViaHost(
  opts: ImageRequest & { model: string; person_card?: Record<string, string>; genre?: string },
): Promise<{
  ok: boolean;
  message?: string;
  image_data_url?: string;
  image_url?: string;
  images?: string[];
  seed?: number;
  seed_sent?: boolean;
}> {
  const token = bridgeToken();
  const aspect = String(opts.aspect || "").toLowerCase();
  // 本机端点只认 width/height；把画布画幅翻译过去，避免竖屏短剧默认出方图。
  // 分辨率总闸（2026-10-27）：画质档决定长边上限，后端会按真实模型再收口一次
  const size: { width?: number; height?: number } = estimateImageSize(
    aspect,
    opts.quality || "standard",
  );
  try {
    const res = await fetch(`${BRIDGE}/host/local-image-generate`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        action: "generate",
        token,
        prompt: opts.prompt,
        model_id: opts.model,
        image: opts.reference_image || "",
        quality: opts.quality || "standard",
        seed: opts.seed ?? 0,
        // C 项：人物卡（后端按固定顺序拼英文提示词，优先于自由文本）
        person_card: opts.person_card || undefined,
        // B 项：题材分档（负向词库）；空则由后端按提示词猜
        genre: opts.genre || "",
        ...size,
      }),
    });
    const data = await res.json();
    return {
      ok: Boolean(data.ok),
      message: String(data.message || ""),
      image_data_url: String(data.image_data_url || ""),
      image_url: String(data.image_url || data.path || ""),
      images: data.images || (data.image_url ? [data.image_url] : []),
      seed: typeof data.seed === "number" ? data.seed : undefined,
      seed_sent: data.seed_sent,
    };
  } catch (e) {
    return { ok: false, message: `本地图像生成请求失败：${String(e)}` };
  }
}

/** 云端/本地统一入口，调用方只负责提供 channel_id::model。 */
export async function generateImageUnified(
  opts: ImageRequest & {
    parsed: { channel_id: string; model: string };
    person_card?: Record<string, string>;
    genre?: string;
  },
): Promise<Awaited<ReturnType<typeof generateImageViaHost>>> {
  const { parsed, ...request } = opts;
  if (parsed.channel_id !== LOCAL_CHANNEL_ID) {
    const cloud = await generateImageViaHost({ ...request, model: parsed.model, channel_id: parsed.channel_id });
    // 2026-11-01：云端"没有可用渠道"时不把用户卡死在墙上 —— 本机能出图就自动改走本地，
    // 并**如实说明**换了路（项目禁止静默降级，所以消息里必须出现原因）。
    // 触发场景（实测）：密钥库写盘失败 ⇒ deepseek 等渠道按未配置处理，
    // 但 selectedModelKey 仍停在云端条目 ⇒ 每次点「生成」都撞同一堵墙。
    if (!cloud.ok && (cloud as { fallback_placeholder?: boolean }).fallback_placeholder) {
      const local = await generateImageLocalViaHost({ ...request, model: "" });
      if (local.ok) {
        return {
          ...local,
          message: `云端渠道不可用（${cloud.message || "未配置 Key"}）⇒ 已自动改用**本地引擎**。${local.message || ""}`,
        };
      }
      return {
        ...cloud,
        message: `${cloud.message || "云端渠道不可用"}；本地引擎也失败：${local.message || "未知原因"}`,
      };
    }
    return cloud;
  }
  const count = Math.max(1, Math.min(4, request.n || 1));
  if (count === 1) return generateImageLocalViaHost({ ...request, model: parsed.model });
  // 本地引擎每次只产一张；多张按抽卡语义逐张生成，不能把第一张重复 count 次。
  const images: string[] = [];
  const seeds: number[] = [];
  let lastMessage = "";
  for (let i = 0; i < count; i++) {
    const one = await generateImageLocalViaHost({ ...request, n: 1, model: parsed.model });
    lastMessage = one.message || lastMessage;
    const url = one.image_data_url || one.image_url;
    if (one.ok && url) {
      images.push(url);
      if (typeof one.seed === "number") seeds.push(one.seed);
    }
  }
  return {
    ok: images.length > 0,
    images,
    image_data_url: images[0],
    seeds,
    message: images.length ? `本地批量生图 ${images.length}/${count}` : lastMessage || "本地生图失败",
    fallback_placeholder: images.length === 0,
  };
}
