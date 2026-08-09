// AboutPage.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AboutPage } from "./AboutPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <AboutPage />
    </MemoryRouter>,
  );
}

describe("AboutPage", () => {
  it("greets the user as MILO with its full name", () => {
    renderPage();
    expect(screen.getByText("Hi, I'm MILO.")).toBeInTheDocument();
    expect(screen.getByText("Memory Integrated Language Oriented Robot")).toBeInTheDocument();
  });

  it("explains every stage of the MILO pipeline", () => {
    renderPage();
    for (const stage of [
      "Perceive",
      "Understand",
      "Remember",
      "Plan",
      "Navigate",
      "Act",
      "Reflect",
      "Replan",
      "Learn",
    ]) {
      expect(screen.getByText(stage)).toBeInTheDocument();
    }
  });

  it("links to Home, Mission Control, and MILO Lab", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Mission Control" })).toHaveAttribute(
      "href",
      "/mission-control",
    );
    expect(screen.getByRole("link", { name: "MILO Lab" })).toHaveAttribute("href", "/lab");
  });
});
