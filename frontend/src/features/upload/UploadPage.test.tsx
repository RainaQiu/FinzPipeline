import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadPage } from "./UploadPage";
import { renderWithClient } from "../../test/render";

describe("UploadPage", () => {
  it("keeps the empty state explicit before a file is selected", () => {
    renderWithClient(<UploadPage />);

    expect(screen.getByText("No file selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload and preview" })).toBeDisabled();
  });

  it("reports a readable API error when upload fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { message: "Only CSV and XLSX uploads are supported." } }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithClient(<UploadPage />);

    await user.upload(
      screen.getByLabelText("Choose source file"),
      new File(["bad"], "ledger.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and preview" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only CSV and XLSX uploads are supported.",
    );
  });
});
