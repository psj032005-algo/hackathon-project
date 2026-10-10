import TrackOrderForm from "./track-order-form";

export const instant = false;

export default async function TrackOrderPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <TrackOrderForm slug={slug} />;
}
