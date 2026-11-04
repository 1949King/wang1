import { describe, expect, it } from "vitest";

import { PET_FRAMES, pickFrame, readyExtraFrames, resolvedFrame, frameUrl } from "./mascotFrames";

describe("mascotFrames（表情帧清单与回落）", () => {
  it("必备三帧已就绪，且文件名固定为 pet_<id>.png", () => {
    expect(PET_FRAMES.neutral.ready).toBe(true);
    expect(PET_FRAMES.blink.ready).toBe(true);
    expect(PET_FRAMES.cheer.ready).toBe(true);
    expect(PET_FRAMES.neutral.file).toBe("pet_neutral.png");
    expect(PET_FRAMES.blink.file).toBe("pet_blink.png");
    expect(PET_FRAMES.cheer.file).toBe("pet_cheer.png");
  });

  it("状态 → 首选帧：睡眠优先、思考/失败/期待各有首选", () => {
    expect(pickFrame("idle", true)).toBe("sleepy");
    expect(pickFrame("thinking", true)).toBe("sleepy");
    expect(pickFrame("thinking", false)).toBe("thinking");
    expect(pickFrame("awaiting", false)).toBe("surprised");
    expect(pickFrame("error", false)).toBe("sad");
    expect(pickFrame("success", false)).toBe("cheer");
    expect(pickFrame("idle", false)).toBe("neutral");
  });

  it("缺素材时诚实回落 neutral，绝不给空图", () => {
    // 待生成帧在 ready=false 时一律回落
    for (const id of ["thinking", "sleepy", "sad", "surprised", "proud"] as const) {
      if (!PET_FRAMES[id].ready) {
        expect(resolvedFrame(id)).toBe("neutral");
      }
    }
    // 已就绪帧保持原样
    expect(resolvedFrame("cheer")).toBe("cheer");
    expect(resolvedFrame("neutral")).toBe("neutral");
  });

  it("额外帧列表只含已就绪的非基础帧，且不重复", () => {
    const extras = readyExtraFrames();
    expect(extras).toContain("cheer");
    expect(extras).not.toContain("neutral");
    expect(extras).not.toContain("blink");
    expect(new Set(extras).size).toBe(extras.length);
    for (const id of extras) {
      expect(PET_FRAMES[id].ready).toBe(true);
    }
  });

  it("frameUrl 指向 public/mascot/ 且以 .png 结尾", () => {
    for (const id of Object.keys(PET_FRAMES) as (keyof typeof PET_FRAMES)[]) {
      const url = frameUrl(id);
      expect(url).toContain("mascot/");
      expect(url.endsWith(".png")).toBe(true);
      expect(url).toContain(PET_FRAMES[id].file);
    }
  });
});
