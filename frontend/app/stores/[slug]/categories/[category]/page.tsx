import PublicStorePage from "../../storefront-client";

export const instant = false;

export default async function StoreCategoryPage({ params }: { params: Promise<{ slug: string; category: string }> }) {
  const { slug, category } = await params;
  return <PublicStorePage slug={slug} initialCategory={category} />;
}
