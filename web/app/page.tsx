import NewRunForm from "@/components/NewRunForm";

export default function HomePage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Turn an article into posts you can trust</h1>
        <p className="mt-2 text-stone-600 dark:text-stone-400">
          The agent plans from your source, writes for each platform, has an AI judge check every claim, and rewrites weak
          drafts. You approve, edit or reject before anything is scheduled.
        </p>
      </div>
      <NewRunForm />
    </div>
  );
}
