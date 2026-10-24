/** 本地图工具：裁剪 / 宫格拆分 / 放大 / 旋转 */
export async function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片加载失败"));
    img.src = url;
  });
}

export function canvasToDataUrl(canvas: HTMLCanvasElement, type = "image/png") {
  return canvas.toDataURL(type);
}

/** 居中裁剪为指定比例 */
export async function cropCenter(url: string, aspectW: number, aspectH: number) {
  const img = await loadImage(url);
  const target = aspectW / aspectH;
  let tw = img.width;
  let th = img.height;
  if (tw / th > target) {
    tw = Math.round(th * target);
  } else {
    th = Math.round(tw / target);
  }
  const sx = Math.floor((img.width - tw) / 2);
  const sy = Math.floor((img.height - th) / 2);
  const c = document.createElement("canvas");
  c.width = tw;
  c.height = th;
  const ctx = c.getContext("2d")!;
  ctx.drawImage(img, sx, sy, tw, th, 0, 0, tw, th);
  return canvasToDataUrl(c);
}

/** 宫格拆成 N×N 张 */
export async function splitGrid(url: string, n: 2 | 3): Promise<string[]> {
  const img = await loadImage(url);
  const cw = Math.floor(img.width / n);
  const ch = Math.floor(img.height / n);
  const out: string[] = [];
  for (let row = 0; row < n; row++) {
    for (let col = 0; col < n; col++) {
      const c = document.createElement("canvas");
      c.width = cw;
      c.height = ch;
      c.getContext("2d")!.drawImage(img, col * cw, row * ch, cw, ch, 0, 0, cw, ch);
      out.push(canvasToDataUrl(c));
    }
  }
  return out;
}

/** 从源图裁出指定格（0-based，行优先） */
export async function cropGridCell(
  url: string,
  cols: number,
  rows: number,
  index: number,
): Promise<string> {
  const img = await loadImage(url);
  const c = Math.max(1, Math.floor(cols));
  const r = Math.max(1, Math.floor(rows));
  const i = Math.max(0, Math.min(c * r - 1, Math.floor(index)));
  const col = i % c;
  const row = Math.floor(i / c);
  const cw = Math.floor(img.width / c);
  const ch = Math.floor(img.height / r);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, cw);
  canvas.height = Math.max(1, ch);
  canvas.getContext("2d")!.drawImage(img, col * cw, row * ch, cw, ch, 0, 0, canvas.width, canvas.height);
  return canvasToDataUrl(canvas);
}

/** 本地放大（双线性），非神经网络超分 */
export async function upscaleLocal(url: string, scale = 2) {
  const img = await loadImage(url);
  const c = document.createElement("canvas");
  c.width = Math.round(img.width * scale);
  c.height = Math.round(img.height * scale);
  const ctx = c.getContext("2d")!;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, c.width, c.height);
  return canvasToDataUrl(c);
}

export async function rotateImage(url: string, deg: 90 | 180 | 270) {
  const img = await loadImage(url);
  const rad = (deg * Math.PI) / 180;
  const swap = deg === 90 || deg === 270;
  const c = document.createElement("canvas");
  c.width = swap ? img.height : img.width;
  c.height = swap ? img.width : img.height;
  const ctx = c.getContext("2d")!;
  ctx.translate(c.width / 2, c.height / 2);
  ctx.rotate(rad);
  ctx.drawImage(img, -img.width / 2, -img.height / 2);
  return canvasToDataUrl(c);
}
