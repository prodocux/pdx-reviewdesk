import { describe, expect, it } from "vitest";
import { hostLabel, waitMessage } from "../lib/waitCopy";

describe("long-wait copy", () => {
  it("separates host wake from ProDocuX after a few seconds", () => {
    expect(waitMessage(1, "wake")).toContain("Checking the hosted API");
    expect(waitMessage(12, "wake")).toContain("Waking Render Free");
    expect(waitMessage(12, "wake")).toContain("not the checks");
    expect(waitMessage(2, "upload")).toContain("Uploading PDFs");
    expect(waitMessage(31, "upload")).toContain("31s");
    expect(waitMessage(31, "upload")).toContain("few hundred milliseconds");
  });

  it("labels the empty desk from health state", () => {
    expect(hostLabel("waking")).toBe("Hosted API waking");
    expect(hostLabel("ready")).toContain("API warm");
  });
});
