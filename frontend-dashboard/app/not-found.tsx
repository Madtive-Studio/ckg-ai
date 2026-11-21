import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm text-center">
        <CardHeader>
          <p className="text-5xl font-bold text-[var(--muted-foreground)]">404</p>
          <CardTitle>Halaman tidak ditemukan</CardTitle>
          <CardDescription>
            Halaman yang Anda buka tidak ada.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link href="/">Kembali ke beranda</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
