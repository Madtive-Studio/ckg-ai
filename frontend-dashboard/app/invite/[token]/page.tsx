import { use } from "react";
import type { Metadata } from "next";
import { InviteAsikForm } from "@/components/invite/invite-asik-form";

// Public (no login): the link token is the credential, so keep it out of search indexes and
// Referer headers.
export const metadata: Metadata = {
  title: "Kredensial ASIK",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <InviteAsikForm token={token} />
    </div>
  );
}
