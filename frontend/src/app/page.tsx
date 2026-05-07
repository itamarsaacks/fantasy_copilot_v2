import { redirect } from "next/navigation";

export default function HomePage() {
  // Default landing is the chat surface — that's the product.
  redirect("/chat");
}
