import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReconciliationPage } from "./ReconciliationPage";
import { renderWithClient } from "../../test/render";

describe("ReconciliationPage", () => {
  it("describes reconciliation differences with text, not color alone", async () => {
    const result = {
      id: "rec-1",
      status: "difference",
      start_date: "2026-04-01",
      end_date: "2026-06-30",
      lines: [
        {
          account_number: "4000",
          internal_minor: 1250000,
          qbo_minor: 1240000,
          difference_minor: 10000,
          status: "difference",
          diagnostic_candidates: ["Check missing or duplicated QBO rows"],
        },
      ],
      internal_totals: {
        revenue_minor: 1250000,
        cogs_minor: 0,
        gross_profit_minor: 1250000,
        operating_expenses_minor: 0,
        net_profit_minor: 1250000,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(result), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithClient(<ReconciliationPage />);

    fireEvent.change(screen.getByLabelText("QBO Profit and Loss JSON"), {
      target: { value: '{"Rows":{"Row":[]}}' },
    });
    await user.click(screen.getByRole("button", { name: "Run local reconciliation" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Mismatch")).toBeInTheDocument();
    expect(screen.getByText("Difference: $100.00")).toBeInTheDocument();
    expect(screen.getByText("Check missing or duplicated QBO rows")).toBeInTheDocument();
  });
});
