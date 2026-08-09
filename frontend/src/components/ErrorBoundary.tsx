// ErrorBoundary.tsx
//
// Purpose
// -------
// Last line of defense wrapped around every routed page (spec Part 11:
// "Do not allow uncaught API errors to crash the application"). Class
// component because React error boundaries have no hook equivalent.
// Deliberately generic/page-agnostic -- individual pages/contexts are
// still responsible for catching their own expected failures (a 503
// from an unavailable agent, a rejected `fetch`) and rendering a real
// empty/error state; this only catches what *those* layers failed to
// catch, so the rest of the MILO app (nav, other pages) keeps working.
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("milo.unhandled_render_error", error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <section className="error-boundary" role="alert">
          <h2 className="error-boundary__title">Something went wrong</h2>
          <p className="error-boundary__message">
            MILO ran into an unexpected problem rendering this page. This has been logged; the
            rest of the app should still work.
          </p>
          <button type="button" className="error-boundary__button" onClick={this.reset}>
            Try again
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
