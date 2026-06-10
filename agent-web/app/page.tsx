import Assistant from "@/components/assistant";

export default function Home() {
  return (
    <main className="box-border h-full overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.9),_rgba(233,239,245,0.92)_42%,_rgba(212,223,233,0.86)_100%)] px-3 py-3 text-foreground sm:px-4 sm:py-4">
      <div className="mx-auto flex h-full max-w-4xl flex-col">
        <Assistant />
      </div>
    </main>
  );
}
