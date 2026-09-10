/**
 * Vocabulary format & parser helpers.
 *
 * A Meeting's `vocabulary` field primes the Transcriber with domain terms and known speaker names.
 * When both are present, they are structured as:
 *   Speakers: Alice, Bob
 *   Vocabulary: term1, term2
 *
 * If only speakers or only terms are present, or legacy unformatted text is loaded,
 * these helpers parse and merge them gracefully without data loss.
 */

export interface ParsedVocabulary {
  speakers: string[];
  vocabulary: string;
}

export function parseVocabulary(raw: string | null | undefined): ParsedVocabulary {
  if (!raw) return { speakers: [], vocabulary: "" };
  const text = raw.trim();
  if (!text) return { speakers: [], vocabulary: "" };

  const lines = text.split("\n");
  const speakerLines: string[] = [];
  const termLines: string[] = [];

  let inTermsBlock = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    const speakerMatch = trimmed.match(/^(?:speakers?|participantes?):\s*(.*)$/i);
    const termsMatch = trimmed.match(/^(?:terms?|vocabulary|termos|vocabulário):\s*(.*)$/i);

    if (speakerMatch) {
      inTermsBlock = false;
      if (speakerMatch[1].trim()) {
        speakerLines.push(speakerMatch[1].trim());
      }
    } else if (termsMatch) {
      inTermsBlock = true;
      if (termsMatch[1].trim()) {
        termLines.push(termsMatch[1].trim());
      }
    } else if (inTermsBlock) {
      termLines.push(trimmed);
    } else {
      termLines.push(trimmed);
    }
  }

  const speakers: string[] = [];
  const seenLower = new Set<string>();
  for (const sl of speakerLines) {
    for (const name of sl.split(/[,;]+/)) {
      const clean = name.trim();
      if (clean && !seenLower.has(clean.toLowerCase())) {
        seenLower.add(clean.toLowerCase());
        speakers.push(clean);
      }
    }
  }

  const vocabulary = termLines.join("\n").trim();
  return { speakers, vocabulary };
}

export function formatVocabulary(speakers: string[], vocabulary: string): string | null {
  const cleanSpeakers = speakers.map((s) => s.trim()).filter(Boolean);
  const cleanVocab = vocabulary.trim();

  const parts: string[] = [];
  if (cleanSpeakers.length > 0) {
    parts.push(`Speakers: ${cleanSpeakers.join(", ")}`);
  }
  if (cleanVocab) {
    if (/^(?:terms?|vocabulary|termos|vocabulário):/i.test(cleanVocab)) {
      parts.push(cleanVocab);
    } else {
      parts.push(`Vocabulary: ${cleanVocab}`);
    }
  }

  return parts.length > 0 ? parts.join("\n") : null;
}
