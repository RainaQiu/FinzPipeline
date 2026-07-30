import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QboPage } from "./QboPage";
import { renderWithClient } from "../../test/render";

describe("QboPage", () => {
  it("makes the guarded execution boundary explicit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            mode: "demo_local",
            connected: false,
            company_name: null,
            execution_authorized: false,
            transaction_write_network_accessed: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderWithClient(<QboPage />);

    expect(await screen.findByText("Demo/local mode")).toBeInTheDocument();
    expect(screen.getAllByText(/pending outbox/i).length).toBeGreaterThan(0);
    const networkNote = screen
      .getByText(/No QBO transaction write network access has occurred/i)
      .closest(".network-note");
    expect(networkNote).toHaveTextContent(
      "No QBO transaction write network access has occurred. OAuth and read-only verification",
    );
  });

  it("blocks planning when the safety status cannot be verified", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            mode: "demo_local",
            connected: false,
            company_name: null,
            execution_authorized: true,
            transaction_write_network_accessed: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderWithClient(<QboPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "QBO safety status could not be verified",
    );
    expect(
      screen.queryByRole("button", { name: "Build pending outbox plan" }),
    ).not.toBeInTheDocument();
  });

  it("posts a guarded sync plan request and reports the pending items", async () => {
    const fetchMock = vi.fn().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const payload =
          init?.method === "POST" && url.endsWith("/sync")
            ? {
                id: "run-12345678",
                status: "planned",
                execution_authorized: false,
                planned_items: 4,
                item_ids: ["1", "2", "3", "4"],
              }
            : {
                mode: "demo_local",
                connected: false,
                company_name: null,
                execution_authorized: false,
                transaction_write_network_accessed: false,
              };
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: init?.method === "POST" ? 202 : 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithClient(<QboPage />);

    await user.click(
      await screen.findByRole("button", { name: "Build pending outbox plan" }),
    );

    const planResult = (await screen.findByText("4 items planned")).closest(".plan-result");
    expect(planResult).toHaveTextContent(
      "4 items planned Run run-1234 remains pending; writes are disabled.",
    );
    const syncCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/integrations/qbo/sync"),
    );
    expect(syncCall?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({}),
    });
  });
});
