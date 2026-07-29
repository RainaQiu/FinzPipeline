import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("exposes the accounting workstation navigation and main landmark", () => {
    render(
      <MemoryRouter initialEntries={["/review"]}>
        <AppShell>
          <h1>Transaction review</h1>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Upload & Mapping" })).toHaveAttribute(
      "href",
      "/upload",
    );
    expect(screen.getByRole("link", { name: "Transaction Review" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Internal P&L" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "QBO Sync" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconciliation" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("Transaction review");
  });

  it("keeps the shared-demo data handling disclosure visible", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <h1>Dashboard</h1>
        </AppShell>
      </MemoryRouter>,
    );

    const disclosure = screen.getByRole("complementary", {
      name: "Shared demonstration notice",
    });
    expect(disclosure).toHaveTextContent(
      "Shared demonstration environment. Do not upload sensitive or real financial data.",
    );
    expect(disclosure).toHaveTextContent(
      /Authentication, tenant isolation, and per-user data separation are intentionally outside/i,
    );
  });
});
