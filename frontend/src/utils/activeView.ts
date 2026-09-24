/**
 * Tracks which view (here: which Meeting page) is on screen, so async work started for
 * an earlier one can tell it is stale.
 *
 * `show()` starts a view and returns its `isCurrent` check; `hide(check)` ends it.
 * `capture()` returns the check for whatever view is on screen now, or null if none.
 */
export class ActiveView {
  private token: object | null = null;

  show(): () => boolean {
    const token = {};
    this.token = token;
    return () => this.token === token;
  }

  hide(isCurrent: () => boolean): void {
    if (isCurrent()) this.token = null;
  }

  capture(): (() => boolean) | null {
    const token = this.token;
    return token ? () => this.token === token : null;
  }
}
