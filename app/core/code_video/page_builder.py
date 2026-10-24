# -*- coding: utf-8 -*-
"""合成时间线页面生成器（V4.45 · 2026-10-19）

输入：`compile_spec()` 产出的 compiled + 已解析 html 文本 + 已解析 asset 绝对路径
输出：一个自包含 HTML 文档（字符串）。**纯函数、零 I/O、零 Qt/ffmpeg 依赖**。

页面职责（渲染 worker 只负责驱动，不重复实现）：
1. 按轨道叠层（z-index 由轨道顺序决定），按 range 显隐；
2. 视频/图片层按 fit 映射（cover / contain / blur-fill）；
3. HTML 镜头以 `iframe srcdoc` 内联（同源可写、脚本可控），并在 srcdoc 最前注入
   **确定性时钟**（performance.now / Date.now / rAF 时间戳 / CSS 动画冻结 / Math.random 按 t 播种）；
4. 暴露 `window.__sgSeek(t)`：同一 t 永远同一帧（视频 seek + iframe 时钟 + 双 rAF 收尾）；
5. 暴露 `window.__sgReady`（字体/视频元数据/iframe 加载）与 `window.__sgTextRects`（QC 用）。

⚠️ 为什么 iframe 用 postMessage 而不是直接读 contentWindow（2026-10-19 实测）：
页面经 `file://` 打开时，Chromium 把 iframe 视为 opaque origin，
父页面访问 `iframe.contentWindow.performance` / `__sgSetT` 会抛 SecurityError。
postMessage 是跨源也成立的唯一通道；同时把文字 rect 一并回传，QC 不需要读 iframe DOM。

安全前提：`security.py` 已保证 html 文本自包含；本模块不信任它们，
但也不再做网络拦截（那是 worker 的 page.route 兜底 + security 的静态闸）。
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List


# ============================================================
# JSON / HTML 转义
# ============================================================

def _json_for_script(obj: Any) -> str:
    """把对象序列化进 <script> 内：转义 </ 防提前闭合，转义 U+2028/2029。"""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _file_uri(path: str) -> str:
    """绝对路径 → file URI（Windows 盘符 / 空格 / 中文均由 pathlib 处理）。"""
    return Path(path).resolve().as_uri()


# ============================================================
# 确定性时钟（注入 iframe srcdoc 最前）
# ============================================================

_CLOCK_JS = r"""
(function () {
  var __t = 0;
  var __epoch = 1700000000000;  // 固定基准，Date.now 也随 t 走
  function seedFromT(t) {
    var x = (Math.floor(t * 1000) | 0) ^ 0x9e3779b9;
    return function () {
      x = (x + 0x6D2B79F5) | 0;
      var r = Math.imul(x ^ (x >>> 15), 1 | x);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }
  var __rand = seedFromT(0);
  Math.random = function () { return __rand(); };
  performance.now = function () { return __t * 1000; };
  Date.now = function () { return __epoch + __t * 1000; };
  var __raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function (cb) {
    return __raf(function () { cb(__t * 1000); });
  };
  window.__sgSetT = function (t) {
    __t = Number(t) || 0;
    __rand = seedFromT(__t);
    var anims = document.getAnimations ? document.getAnimations() : [];
    for (var i = 0; i < anims.length; i++) {
      try { anims[i].pause(); anims[i].currentTime = __t * 1000; } catch (e) {}
    }
    if (typeof window.__sgFrame === 'function') {
      try { window.__sgFrame(__t); } catch (e) {}
    }
  };
  function textRects() {
    var out = [];
    var els = document.querySelectorAll('[data-sg-text]');
    for (var i = 0; i < els.length; i++) {
      var r = els[i].getBoundingClientRect();
      out.push({
        x: r.x, y: r.y, width: r.width, height: r.height,
        text: String(els[i].textContent || '').slice(0, 60)
      });
    }
    return out;
  }
  window.addEventListener('message', function (e) {
    var d = e.data || {};
    if (!d || d.__sg !== 'seek' || !e.source) return;
    window.__sgSetT(Number(d.t) || 0);
    try {
      e.source.postMessage({ __sg: 'seeked', id: d.id, t: Number(d.t) || 0 }, '*');
      e.source.postMessage({ __sg: 'textRects', id: d.id, rects: textRects() }, '*');
    } catch (err) {}
  });
  function announce() {
    try { window.parent.postMessage({ __sg: 'ready' }, '*'); } catch (e) {}
  }
  announce();
  document.addEventListener('DOMContentLoaded', announce);
})();
"""


def inject_clock(html_text: str) -> str:
    """在用户 HTML 的 <head> 后（无 head 则 <html> 后/最前）注入确定性时钟。"""
    return _inject_raw(html_text, "<script>" + _CLOCK_JS + "<" + "/script>")


def _inject_raw(html_text: str, snippet: str) -> str:
    lower = html_text.lower()
    head = lower.find("<head")
    if head >= 0:
        close = lower.find(">", head)
        if close >= 0:
            return html_text[: close + 1] + snippet + html_text[close + 1:]
    html = lower.find("<html")
    if html >= 0:
        close = lower.find(">", html)
        if close >= 0:
            return html_text[: close + 1] + snippet + html_text[close + 1:]
    return snippet + html_text


# ============================================================
# 图层 HTML
# ============================================================

def _fit_class(fit: str) -> str:
    return "sg-fit-blur" if fit == "blur-fill" else f"sg-fit-{fit}"


def _media_layer(clip: Dict[str, Any], asset_path: str, asset_kind: str) -> str:
    uri = escape(_file_uri(asset_path), quote=True)
    cid = escape(str(clip.get("id", "")), quote=True)
    fit = _fit_class(str(clip.get("fit") or "cover"))
    if asset_kind == "image":
        fg = f'<img class="sg-media sg-fg" src="{uri}" alt="">'
        bg = f'<img class="sg-media sg-bg" src="{uri}" alt="">'
    else:
        fg = (
            f'<video class="sg-media sg-fg" src="{uri}" muted playsinline '
            f'preload="auto"></video>'
        )
        bg = (
            f'<video class="sg-media sg-bg" src="{uri}" muted playsinline '
            f'preload="auto"></video>'
        )
    inner = (bg + fg) if fit == "sg-fit-blur" else fg
    return f'<div class="sg-layer {fit}" data-clip="{cid}">{inner}</div>'


def _html_layer(clip: Dict[str, Any]) -> str:
    cid = escape(str(clip.get("id", "")), quote=True)
    src = escape(str(clip.get("source", "")), quote=True)
    return (
        f'<div class="sg-layer sg-html" data-clip="{cid}" data-source="{src}">'
        f'<iframe class="sg-iframe" sandbox="allow-scripts" title="{cid}"></iframe>'
        f"</div>"
    )


# ============================================================
# 页面模板
# ============================================================

_CSS = """
html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:__BG__;}
#sg-stage{position:relative;width:100vw;height:100vh;overflow:hidden;}
.sg-layer{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}
.sg-media{width:100%;height:100%;display:block;}
.sg-fit-cover .sg-media{object-fit:cover;}
.sg-fit-contain .sg-media{object-fit:contain;}
.sg-fit-blur{position:absolute;inset:0;}
.sg-fit-blur .sg-bg{position:absolute;inset:0;object-fit:cover;filter:blur(24px);transform:scale(1.12);}
.sg-fit-blur .sg-fg{position:relative;z-index:1;object-fit:contain;}
.sg-html{position:absolute;inset:0;}
.sg-iframe{width:100%;height:100%;border:0;background:transparent;display:block;}
"""

_RUNTIME_JS = r"""
(function () {
  var SPEC = window.__SG_SPEC__ || {};
  var HTMLS = window.__SG_HTML__ || {};
  var CLIPS = {};
  (SPEC.tracks || []).forEach(function (item) {
    var c = item.clip || {};
    CLIPS[c.id] = c;
    var layer = document.querySelector('[data-clip="' + c.id + '"]');
    if (!layer) return;
    layer.style.zIndex = String(10 + (item.z || 0));
    if (layer.classList.contains('sg-html')) {
      var frame = layer.querySelector('iframe');
      if (frame && HTMLS[c.source] != null) {
        frame.srcdoc = window.__sgInjectClock(HTMLS[c.source], c.params || {});
      }
    }
  });

  var textRects = [];
  var pending = {};
  var seq = 0;
  window.__sgTextRects = [];
  window.addEventListener('message', function (e) {
    var d = e.data || {};
    if (!d || !d.__sg) return;
    if (d.__sg === 'textRects') { textRects = d.rects || []; window.__sgTextRects = textRects; }
    if (d.__sg === 'seeked') {
      var done = pending[d.id];
      if (done) { delete pending[d.id]; done(); }
    }
  });

  var vids = Array.prototype.slice.call(document.querySelectorAll('video'));
  var frames = Array.prototype.slice.call(document.querySelectorAll('iframe'));
  window.__sgReady = Promise.all(
    vids.map(function (v) {
      return new Promise(function (res) {
        if (v.readyState >= 2) return res();
        v.addEventListener('loadeddata', function () { res(); }, { once: true });
        v.addEventListener('error', function () { res(); }, { once: true });
      });
    }).concat(
      frames.map(function (f) {
        return new Promise(function (res) {
          f.addEventListener('load', function () { res(); }, { once: true });
          setTimeout(res, 3000);
        });
      }),
      [(document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve()]
    )
  );

  function seekVideo(el, t, c) {
    var sr = c.source_range || null;
    var speed = c.speed || 1;
    var local = (t - c.range[0]) * speed;
    var start = sr ? sr[0] : 0;
    var end = sr ? sr[1] : start + (c.range[1] - c.range[0]) * speed;
    var st = Math.max(start, Math.min(start + local, end - 0.001));
    return new Promise(function (res) {
      if (Math.abs(el.currentTime - st) <= 1e-4) return res();
      var done = false;
      function fin() { if (done) return; done = true; el.removeEventListener('seeked', fin); res(); }
      el.addEventListener('seeked', fin);
      try { el.currentTime = st + 0.001; } catch (e) { fin(); }
      setTimeout(fin, 1000);
    });
  }

  function seekFrame(frame, t) {
    return new Promise(function (res) {
      var id = ++seq;
      pending[id] = res;
      try {
        frame.contentWindow.postMessage({ __sg: 'seek', t: t, id: id }, '*');
      } catch (e) {
        delete pending[id];
        return res();
      }
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; res(); }
      }, 800);
    });
  }

  window.__sgSeek = function (t) {
    var waits = [];
    Array.prototype.forEach.call(document.querySelectorAll('[data-clip]'), function (el) {
      var c = CLIPS[el.getAttribute('data-clip')];
      if (!c) return;
      var visible = t >= c.range[0] - 1e-6 && t < c.range[1] - 1e-6;
      el.style.display = visible ? '' : 'none';
      if (!visible) return;
      if (el.classList.contains('sg-html')) {
        var frame = el.querySelector('iframe');
        if (frame) waits.push(seekFrame(frame, t));
        return;
      }
      Array.prototype.forEach.call(el.querySelectorAll('video'), function (v) {
        waits.push(seekVideo(v, t, c));
      });
    });
    return Promise.all(waits).then(function () {
      return new Promise(function (res) {
        requestAnimationFrame(function () { requestAnimationFrame(res); });
      });
    });
  };
})();
"""


def build_timeline_page(
    compiled: Dict[str, Any],
    html_contents: Dict[str, str],
    asset_paths: Dict[str, str],
) -> str:
    """生成合成时间线页面（供 render_worker 用 file:// 打开）。

    compiled: compile_spec() 产物；html_contents: `html://name` → 文本；
    asset_paths: assets 键（如 shot_1.mp4）→ inbox 内绝对路径。
    """
    canvas = compiled.get("canvas") or {}
    width = int(canvas.get("width") or 1080)
    height = int(canvas.get("height") or 1920)
    bg = str(canvas.get("background") or "#000000")

    layers: List[str] = []
    visual_tracks: List[Dict[str, Any]] = []
    for item in compiled.get("tracks") or []:
        clip = (item or {}).get("clip") or {}
        if not clip:
            continue
        kind = str(clip.get("kind") or "video")
        if kind == "audio":
            continue  # 音频由 ffmpeg 单独合成，不进画面
        source = str(clip.get("source") or "")
        if source.startswith("html://"):
            layers.append(_html_layer(clip))
        elif source.startswith("asset://"):
            key = source[len("asset://"):]
            path = asset_paths.get(key)
            if not path:
                continue  # security.resolve_assets 已报错；这里不造占位图
            entry = (compiled.get("assets") or {}).get(key) or {}
            layers.append(_media_layer(clip, path, str(entry.get("kind") or "video")))
        else:
            continue
        visual_tracks.append({"clip": clip, "z": len(visual_tracks) + 1})

    spec_for_js = {"canvas": canvas, "tracks": visual_tracks}

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width={width},height={height}">
<style>#sg-stage{{width:{width}px;height:{height}px;}}
{_CSS.replace("__BG__", bg)}</style>
</head><body>
<div id="sg-stage">{"".join(layers)}</div>
<script>
window.__SG_SPEC__ = {_json_for_script(spec_for_js)};
window.__SG_HTML__ = {_json_for_script(html_contents)};
window.__SG_CLOCK__ = {_json_for_script(_CLOCK_JS)};
window.__sgInjectClock = function (html, params) {{
  var payload = JSON.stringify(params || {{}}).replace(/<\\//g, '<\\\\/');
  var snip = '<script>window.__sgParams = ' + payload + ';</scr' + 'ipt>'
           + '<script>' + window.__SG_CLOCK__ + '</scr' + 'ipt>';
  var lower = String(html || '').toLowerCase();
  var at = lower.indexOf('<head');
  if (at >= 0) {{ var close = lower.indexOf('>', at); if (close >= 0) return html.slice(0, close + 1) + snip + html.slice(close + 1); }}
  at = lower.indexOf('<html');
  if (at >= 0) {{ var c2 = lower.indexOf('>', at); if (c2 >= 0) return html.slice(0, c2 + 1) + snip + html.slice(c2 + 1); }}
  return snip + html;
}};
</script>
<script>{_RUNTIME_JS}</script>
</body></html>"""
