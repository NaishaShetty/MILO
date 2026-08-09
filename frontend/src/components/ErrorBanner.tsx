// ErrorBanner.tsx
//
// Purpose
// -------
// Renders a safe, user-readable message for every failure case this
// UI can encounter: invalid input, a provider outage, a timeout, or an
// internal error -- distinguished by `LanguageApiError.category` (see
// `src/api/language.ts`), each mapped to one short, non-technical
// title below in `_TITLES`. Never renders a stack trace or raw
// exception text -- the backend already guarantees `message` is safe
// to display (see `backend/api/routes/language.py`'s "Error mapping"
// docstring section); this component's only added responsibility is
// picking a category-appropriate title.
import { LanguageApiError } from "../api/language";

interface ErrorBannerProps {
  error: Error;
}

const _TITLES: Record<string, string> = {
  invalid_request: "Invalid Instruction",
  timeout: "Language Service Timed Out",
  provider_unavailable: "Language Service Unavailable",
  configuration_error: "Language Service Misconfigured",
  upstream_invalid_response: "Could Not Understand Instruction",
  internal_error: "Something Went Wrong",
};

const _NETWORK_TITLE = "Cannot Reach Language Service";
const _NETWORK_MESSAGE =
  "The backend could not be reached. Check your connection and try again.";

export function ErrorBanner({ error }: ErrorBannerProps) {
  const isApiError = error instanceof LanguageApiError;
  const title = isApiError ? (_TITLES[error.category] ?? "Something Went Wrong") : _NETWORK_TITLE;
  const message = isApiError ? error.message : _NETWORK_MESSAGE;

  return (
    <div className="banner banner--error" role="alert">
      <p className="banner__title">{title}</p>
      <p className="banner__body">{message}</p>
    </div>
  );
}
