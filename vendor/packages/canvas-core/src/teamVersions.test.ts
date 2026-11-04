/**
 * 历史版本的时间/大小格式（2026-11-04 · 画布 0.3.48）
 *
 * 这两行字是用户判断「该回滚到哪一版」的唯一依据。时间若按 UTC 显示，用户会看到
 * 「11-04 07:20」而自己手表是 15:20 —— 在「昨天那版是不是我要的」这种问题上，
 * 差 8 小时足以让人回滚错版本。所以把「本地时区」这件事锁进测试。
 */
import { describe, expect, it } from "vitest";

import { versionBytes, versionStamp } from "./TeamVersions";

describe("versionStamp", () => {
  it("按本地时区显示「月-日 时:分」，个位数补零", () => {
    const d = new Date(2026, 10, 4, 9, 5, 0);         // 本地 2026-11-04 09:05
    expect(versionStamp(d.getTime() / 1000)).toBe("11-04 09:05");
  });

  it("没有时间（0 / 脏数据）显示破折号，不显示 1970", () => {
    expect(versionStamp(0)).toBe("—");
    expect(versionStamp(Number.NaN)).toBe("—");
  });
});

describe("versionBytes", () => {
  it("按 KB / MB 归并", () => {
    expect(versionBytes(512)).toBe("512B");
    expect(versionBytes(2048)).toBe("2KB");
    expect(versionBytes(3 * 1048576)).toBe("3.0MB");
  });
});
