import { MonitorDashboard } from "@/components/monitor/MonitorDashboard";

// SSE/状態は client で購読する(MonitorDashboard が "use client")。
export default function MonitorPage() {
  return <MonitorDashboard />;
}
