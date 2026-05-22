import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { BottomNav } from "@/components/shell/bottom-nav";
import { DrawerProvider } from "@/components/shared/drawer-context";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DrawerProvider>
      <div className="min-h-dvh flex bg-background">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Topbar />
          <main className="flex-1 min-h-0 overflow-hidden pb-16 md:pb-0">
            {children}
          </main>
          <BottomNav />
        </div>
      </div>
    </DrawerProvider>
  );
}
