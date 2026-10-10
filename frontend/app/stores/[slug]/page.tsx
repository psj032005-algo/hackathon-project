import PublicStorePage from "./storefront-client";

export const instant = false;

export default async function StorePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <PublicStorePage slug={slug} />;
}
