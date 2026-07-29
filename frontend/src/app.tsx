import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { PnlPage } from "./features/pnl/PnlPage";
import { QboPage } from "./features/qbo/QboPage";
import { ReconciliationPage } from "./features/reconciliation/ReconciliationPage";
import { ReviewPage } from "./features/review/ReviewPage";
import { UploadPage } from "./features/upload/UploadPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/pnl" element={<PnlPage />} />
        <Route path="/qbo" element={<QboPage />} />
        <Route path="/reconciliation" element={<ReconciliationPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
