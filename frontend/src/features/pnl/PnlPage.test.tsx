import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PnlPage } from "./PnlPage";
import { renderWithClient } from "../../test/render";

describe("PnlPage", () => {
  it("opens transaction drill-down from an account line", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/accounts/4000/")
        ? {
            account_number: "4000",
            total: 1,
            items: [
              {
                id: "txn-1",
                transaction_date: "2026-04-05",
                description: "Home repair invoice",
                amount_minor: 125000,
                currency: "USD",
                classification: { account_number: "4000" },
              },
            ],
          }
        : {
            start_date: "2026-04-01",
            end_date: "2026-06-30",
            revenue_lines: [
              {
                account_number: "4000",
                account_name: "Repair Service Revenue",
                total_minor: 125000,
                transaction_count: 1,
                transaction_ids: ["txn-1"],
              },
            ],
            cogs_lines: [],
            operating_expense_lines: [],
            account_totals: { "4000": 125000 },
            totals: {
              revenue_minor: 125000,
              cogs_minor: 0,
              gross_profit_minor: 125000,
              operating_expenses_minor: 0,
              net_profit_minor: 125000,
            },
          };
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithClient(<PnlPage />);

    const accountLine = await screen.findByRole("button", {
      name: "Drill into 4000 Repair Service Revenue",
    });
    expect(accountLine).toHaveTextContent("4000 Repair Service Revenue");
    await user.click(accountLine);

    const heading = await screen.findByRole("heading", {
      name: "4000 · Repair Service Revenue",
    });
    const drilldown = heading.closest("aside");
    expect(drilldown).not.toBeNull();
    expect(within(drilldown!).getByText("Home repair invoice")).toBeInTheDocument();
    expect(drilldown).toHaveTextContent("Home repair invoice Apr 5, 2026");
    expect(within(drilldown!).getAllByText("$1,250.00").length).toBeGreaterThan(0);
  });
});
