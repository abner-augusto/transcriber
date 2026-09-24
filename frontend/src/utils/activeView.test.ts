import { describe, expect, it } from "vitest";
import { ActiveView } from "./activeView";

describe("ActiveView", () => {
  it("keeps the shown view current until it is hidden", () => {
    const view = new ActiveView();
    const isCurrent = view.show();
    expect(isCurrent()).toBe(true);
    view.hide(isCurrent);
    expect(isCurrent()).toBe(false);
  });

  it("makes an earlier view stale when a new one is shown", () => {
    const view = new ActiveView();
    const first = view.show();
    const second = view.show();
    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it("does not let hiding a stale view hide the current one", () => {
    const view = new ActiveView();
    const first = view.show();
    const second = view.show();
    view.hide(first);
    expect(second()).toBe(true);
  });

  it("captures nothing after the page has let go", () => {
    const view = new ActiveView();
    const isCurrent = view.show();
    const captured = view.capture();
    view.hide(isCurrent);
    expect(captured?.()).toBe(false);
    expect(view.capture()).toBeNull();
  });
});
