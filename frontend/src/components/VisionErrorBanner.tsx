// VisionErrorBanner.tsx
//
// Purpose
// -------
// Vision-panel counterpart to `ErrorBanner.tsx` -- same shape and same
// "never render raw exception text, only the backend's safe
// category/message" discipline (see that file's docstring), branching
// on `VisionApiError.category` instead of `LanguageApiError.category`.
// A separate component (not a shared generic one) so each panel's error
// vocabulary can evolve independently -- `"vision_unavailable"` (no
// simulator connected) has no Language API equivalent.
import { VisionApiError } from "../api/vision";

interface VisionErrorBannerProps {
  error: Error;
}

const _TITLES: Record<string, string> = {
  invalid_request: "Invalid Detection Prompt",
  vision_unavailable: "Vision System Unavailable",
  internal_error: "Something Went Wrong",
};

const _NETWORK_TITLE = "Cannot Reach Vision Service";
const _NETWORK_MESSAGE =
  "The backend could not be reached. Check your connection and try again.";

export function VisionErrorBanner({ error }: VisionErrorBannerProps) {
  const isApiError = error instanceof VisionApiError;
  const title = isApiError ? (_TITLES[error.category] ?? "Something Went Wrong") : _NETWORK_TITLE;
  const message = isApiError ? error.message : _NETWORK_MESSAGE;

  return (
    <div className="banner banner--error" role="alert">
      <p className="banner__title">{title}</p>
      <p className="banner__body">{message}</p>
    </div>
  );
}
