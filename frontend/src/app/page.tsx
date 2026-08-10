import { redirect } from "next/navigation";
import { cookies } from "next/headers";

/**
 * The root sends people where they belong: signed-in users to their workspace,
 * everyone else to sign-in. Presence of the cookie is enough to decide which —
 * if it turns out to be invalid, the dashboard's own check catches it.
 */
export default async function Home() {
  const cookieStore = await cookies();
  redirect(cookieStore.has("careerhq_session") ? "/dashboard" : "/login");
}
