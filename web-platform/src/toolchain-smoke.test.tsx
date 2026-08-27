import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";

function SmokePanel() {
  return <section aria-label="frontend smoke">React quality gate</section>;
}

describe("React testing toolchain", () => {
  it("renders with React Testing Library", () => {
    render(<SmokePanel />);

    expect(screen.getByLabelText("frontend smoke")).toHaveTextContent(
      "React quality gate",
    );
  });
});
