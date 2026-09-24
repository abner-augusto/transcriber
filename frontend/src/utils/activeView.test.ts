import { describe, expect, it } from "vitest";
import { ActiveView } from "./activeView";

describe("ActiveView", () => {
  it("keeps the shown view current until it is hidden", () => {
    const view = new ActiveView();
    const isCurrent = view.show("a");
    expect(isCurrent()).toBe(true);
    view.hide(isCurrent);
    expect(isCurrent()).toBe(false);
  });

  it("makes an earlier view stale when a new one is shown", () => {
    const view = new ActiveView();
    const first = view.show("a");
    const second = view.show("b");
    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it("does not let hiding a stale view hide the current one", () => {
    const view = new ActiveView();
    const first = view.show("a");
    const second = view.show("b");
    view.hide(first);
    expect(second()).toBe(true);
  });

  it("captures nothing after the page has let go", () => {
    const view = new ActiveView();
    const isCurrent = view.show("a");
    const captured = view.capture("a");
    view.hide(isCurrent);
    expect(captured?.()).toBe(false);
    expect(view.capture("a")).toBeNull();
  });

  it("does not let a caller holding an old key borrow the new view", () => {
    // Duplicate-and-reprocess navigates from Meeting a to b without unmounting the page;
    // a panel's refresh closed over "a" must not fetch a into b's page.
    const view = new ActiveView();
    const first = view.show("a");
    view.hide(first);
    view.show("b");
    expect(view.capture("a")).toBeNull();
    expect(view.capture("b")?.()).toBe(true);
  });
});
