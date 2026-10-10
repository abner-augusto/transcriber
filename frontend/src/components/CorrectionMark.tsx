import { useState } from "react";
import type { Correction } from "../types";
import { confirmCorrection, rejectCorrection } from "../api";
import { apiErrorMessage } from "../utils/apiError";

interface Props {
  segmentId: string;
  correction: Correction;
  /** The Word the Correction produced, as it stands in the Segment's text. */
  children: string;
  /** Called after a confirm or undo succeeded, so the page reloads the Segment. */
  onChanged: () => void;
}

/**
 * A Word that Vocabulary Correction changed, with a popover to confirm or undo it.
 *
 * Opens on hover and on keyboard focus; closes on mouse leave, focus leaving, Escape
 * or after an action. Clicks stop here so they never start editing the Segment's text.
 */
export default function CorrectionMark({ segmentId, correction, children, onChanged }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: typeof confirmCorrection) {
    setBusy(true);
    setError(null);
    try {
      await action(segmentId, correction.start);
      setOpen(false);
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const confirmed = correction.confirmed === true;

  return (
    <span
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
      onKeyDown={(e) => {
        if (open && e.key === "Escape") {
          e.stopPropagation();
          setOpen(false);
        }
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        className={`underline decoration-dotted underline-offset-2 cursor-pointer ${
          confirmed ? "decoration-slate-500/50" : "decoration-cyan-300 decoration-2 bg-cyan-400/10 rounded-sm"
        }`}
      >
        {children}
      </button>
      {open && (
        <span
          role="group"
          aria-label={`Correction of "${correction.heard}"`}
          className="absolute left-0 top-full z-20 block pt-1 text-left"
        >
          <span className="block w-max max-w-xs rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-normal not-italic text-slate-300 shadow-lg">
            <span className="block">
              heard: <span className="text-white">&ldquo;{correction.heard}&rdquo;</span>
            </span>
            <span className="mt-1.5 flex gap-3">
              {!confirmed && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act(confirmCorrection)}
                  title="Teach this form: it will be corrected the same way in future Meetings"
                  className="text-violet-400 hover:text-violet-300 disabled:opacity-40"
                >
                  &#10003; Confirm
                </button>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() => act(rejectCorrection)}
                title="Put back what was heard and never correct this form to this term again"
                className="text-slate-400 hover:text-slate-200 disabled:opacity-40"
              >
                &#8630; Undo
              </button>
            </span>
            {error && <span className="mt-1.5 block text-red-400">{error}</span>}
          </span>
        </span>
      )}
    </span>
  );
}
