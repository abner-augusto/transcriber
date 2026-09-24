/**
 * Tracks which view (here: which Meeting page) is on screen, so async work started for
 * an earlier one can tell it is stale.
 *
 * `show(key)` starts a view and returns its `isCurrent` check; `hide(check)` ends it.
 * `capture(key)` returns the check for the view on screen now, or null if none is shown
 * or it shows a different key: a caller holding an old key must not borrow the new view.
 */
export class ActiveView {
  private current: { key: string } | null = null;

  show(key: string): () => boolean {
    const token = { key };
    this.current = token;
    return () => this.current === token;
  }

  hide(isCurrent: () => boolean): void {
    if (isCurrent()) this.current = null;
  }

  capture(key: string): (() => boolean) | null {
    const token = this.current;
    return token && token.key === key ? () => this.current === token : null;
  }
}
