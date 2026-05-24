import { redirect } from "next/navigation";

// /waivers folded into /trades as the "Pickups" sub-tab (master plan §4
// item 6). Preserve any existing bookmarks/links by redirecting.
export default function WaiversPage() {
  redirect("/trades?tab=pickups");
}
