import Assistant from "@/components/assistant";

export default function Home() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.9),_rgba(233,239,245,0.92)_42%,_rgba(212,223,233,0.86)_100%)] px-4 py-6 text-foreground sm:px-6">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-4xl flex-col justify-center">
        <Assistant />
      </div>
    </main>
  );
}
