// Small plain-language helpers shared by the pages.

/** "Today", "Yesterday", "3 days ago", "Last week" for an epoch-seconds timestamp. */
export function relativeDay(epochSeconds: number, now: number = Date.now() / 1000): string {
  const days = Math.floor((now - epochSeconds) / 86400);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "Last week";
  return `${Math.floor(days / 7)} weeks ago`;
}

/** A plain-language sentence for how sure MILO is about a stored fact. */
export function sureness(confidence: number): { label: string; dots: number } {
  if (confidence >= 0.9) return { label: "Very sure", dots: 5 };
  if (confidence >= 0.7) return { label: "Fairly sure", dots: 4 };
  if (confidence >= 0.5) return { label: "Pretty sure", dots: 3 };
  if (confidence >= 0.3) return { label: "Not sure", dots: 2 };
  return { label: "Just a guess", dots: 1 };
}

/** A short friendly title for a plan step ("Walk to the apple"). */
export function stepTitle(step: { action: string; target?: string | null; parameters?: Record<string, unknown> }): string {
  const t = step.target ? `the ${step.target}` : "it";
  const container = step.parameters?.container ? `the ${String(step.parameters.container)}` : "place";
  switch (step.action) {
    case "locate":
      return `Spot ${t}`;
    case "navigate":
      return ["user", "me", "home"].includes(String(step.target)) ? "Come back to you" : `Walk to ${t}`;
    case "pickup":
      return `Pick up ${t}`;
    case "place":
      return `Put ${t} in ${container}`;
    case "open":
      return `Open ${t}`;
    case "close":
      return `Close ${t}`;
    case "turn_on":
      return `Turn on ${t}`;
    case "turn_off":
      return `Turn off ${t}`;
    default:
      return `Work on ${t}`;
  }
}
