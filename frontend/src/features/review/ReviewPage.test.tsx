import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewPage } from "./ReviewPage";
import { renderWithClient } from "../../test/render";

const transactionPage = {
  items: [
    {
      id: "txn-1",
      raw_record_id: "raw-1",
      bank_transaction_id: "BANK-100",
      transaction_date: "2026-04-05",
      posted_date: "2026-04-06",
      description: "Northwind Materials",
      description_normalized: "northwind materials",
      amount_minor: -248900,
      currency: "USD",
      direction: "outflow",
      bank_account_number: "1000",
      duplicate_status: "possible_duplicate",
      risk: "high",
      classification: {
        id: "class-1",
        transaction_id: "txn-1",
        account_number: "5000",
        transaction_type: "cogs",
        source: "merchant_rule",
        confidence_basis_points: 7200,
        approval_status: "suggested",
        needs_review: true,
        explanation: "Merchant and amount pattern matched materials.",
        version: 1,
        created_at: "2026-04-06T10:00:00Z",
        reviewed_at: null,
      },
    },
  ],
  total: 1,
  offset: 0,
  limit: 50,
};

describe("ReviewPage", () => {
  it("labels risk and confidence in text and opens the selected transaction inspector", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(transactionPage), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const user = userEvent.setup();

    renderWithClient(<ReviewPage />);

    expect(await screen.findByText("Northwind Materials")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("72.00% confidence")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /review northwind materials/i }));

    expect(screen.getByRole("heading", { name: "Classification inspector" })).toBeInTheDocument();
    expect(screen.getByText("Merchant and amount pattern matched materials.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve classification" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Correct classification" })).toBeEnabled();
  });

  it("sends account and duplicate filters to the transaction API", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(transactionPage), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithClient(<ReviewPage />);

    await screen.findByText("Northwind Materials");
    await user.selectOptions(screen.getByLabelText("Account filter"), "6060");
    await user.selectOptions(
      screen.getByLabelText("Duplicate status filter"),
      "possible_duplicate",
    );

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(
        urls.some(
          (url) =>
            url.includes("account=6060") &&
            url.includes("duplicate=possible_duplicate"),
        ),
      ).toBe(true);
    });
  });

  it("updates the selected classification after approval and sends the approve request", async () => {
    const approvedClassification = {
      ...transactionPage.items[0].classification,
      approval_status: "approved",
      needs_review: false,
      version: 2,
    };
    let currentClassification = transactionPage.items[0].classification;
    const fetchMock = vi.fn().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/approve") && init?.method === "POST") {
          currentClassification = approvedClassification;
          return Promise.resolve(
            new Response(JSON.stringify(approvedClassification), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...transactionPage,
              items: [
                {
                  ...transactionPage.items[0],
                  classification: currentClassification,
                },
              ],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithClient(<ReviewPage />);

    await user.click(
      await screen.findByRole("button", { name: /review northwind materials/i }),
    );
    const approveButton = screen.getByRole("button", {
      name: "Approve classification",
    });
    await user.click(approveButton);

    await waitFor(() => expect(approveButton).toBeDisabled());
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input).endsWith("/api/v1/transactions/txn-1/approve") &&
          init?.method === "POST",
      ),
    ).toBe(true);
  });

  it("provides all accounts and keeps focus inside the correction dialog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(transactionPage), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithClient(<ReviewPage />);

    await user.click(
      await screen.findByRole("button", { name: /review northwind materials/i }),
    );
    const trigger = screen.getByRole("button", { name: "Correct classification" });
    await user.click(trigger);

    const account = screen.getByLabelText("Account");
    await waitFor(() => expect(account).toHaveFocus());
    expect(within(account).getAllByRole("option")).toHaveLength(21);
    expect(
      within(account).getByRole("option", { name: "6090 · Office & General" }),
    ).toBeInTheDocument();

    const cancel = screen.getByRole("button", { name: "Cancel" });
    cancel.focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: "Correct classification" }),
    ).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("submits the selected correction payload and refreshes the inspector", async () => {
    const correctedClassification = {
      ...transactionPage.items[0].classification,
      account_number: "6060",
      transaction_type: "operating_expense",
      approval_status: "approved",
      needs_review: false,
      explanation: "Utility bill confirmed from source memo.",
      version: 2,
    };
    let correctionBody: unknown;
    let currentClassification = transactionPage.items[0].classification;
    const fetchMock = vi.fn().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/correct") && init?.method === "POST") {
          correctionBody = JSON.parse(String(init.body));
          currentClassification = correctedClassification;
          return Promise.resolve(
            new Response(JSON.stringify(correctedClassification), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...transactionPage,
              items: [
                {
                  ...transactionPage.items[0],
                  classification: currentClassification,
                },
              ],
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithClient(<ReviewPage />);

    await user.click(
      await screen.findByRole("button", { name: /review northwind materials/i }),
    );
    await user.click(
      screen.getByRole("button", { name: "Correct classification" }),
    );
    await user.selectOptions(screen.getByLabelText("Account"), "6060");
    await user.selectOptions(
      screen.getByLabelText("Transaction type"),
      "operating_expense",
    );
    await user.type(
      screen.getByLabelText("Reason for correction"),
      "Utility bill confirmed from source memo.",
    );
    await user.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Correct classification" }),
      ).not.toBeInTheDocument(),
    );
    expect(correctionBody).toEqual({
      account_number: "6060",
      transaction_type: "operating_expense",
      explanation: "Utility bill confirmed from source memo.",
    });
    const inspector = screen
      .getByRole("heading", { name: "Classification inspector" })
      .closest("aside");
    expect(inspector).not.toBeNull();
    expect(within(inspector!).getByText("6060")).toBeInTheDocument();
    expect(
      within(inspector!).getByText("Utility bill confirmed from source memo."),
    ).toBeInTheDocument();
  });
});
