import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardPage } from "./DashboardPage";
import { renderWithClient } from "../../test/render";

describe("DashboardPage", () => {
  it("reports an unavailable workspace when QBO safety status fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/integrations/qbo/status")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ error: { message: "QBO status unavailable." } }),
              { status: 503, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({ items: [], total: 0, offset: 0, limit: 250 }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }),
    );

    renderWithClient(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "QBO status unavailable.",
    );
    expect(screen.getByText("Workspace status unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Local workspace ready")).not.toBeInTheDocument();
  });
});
