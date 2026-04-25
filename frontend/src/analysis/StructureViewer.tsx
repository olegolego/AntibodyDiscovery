import { useEffect, useRef } from "react";

interface Props {
  pdbText: string;
}

export function StructureViewer({ pdbText }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Store stage in a ref so cleanup works correctly
  const stageRef = useRef<unknown>(null);

  useEffect(() => {
    if (!containerRef.current || !pdbText) return;

    let cancelled = false;

    import("ngl").then((NGL) => {
      if (cancelled || !containerRef.current) return;

      // Destroy any previous stage
      if (stageRef.current) {
        (stageRef.current as { dispose(): void }).dispose();
      }

      const stage = new NGL.Stage(containerRef.current, {
        backgroundColor: "#080c18",
        quality: "medium",
      });
      stageRef.current = stage;

      const blob = new Blob([pdbText], { type: "text/plain" });
      stage
        .loadFile(blob as File, { ext: "pdb", defaultRepresentation: false })
        .then((component) => {
          if (cancelled || !component) return;
          // Cast: NGL types are loose, component is always a StructureComponent here
          const comp = component as unknown as {
            addRepresentation(type: string, params?: object): void;
            autoView(): void;
          };
          comp.addRepresentation("cartoon", {
            colorScheme: "bfactor",
            colorScale: "RdYlBu",
            colorReverse: true,
            smoothSheet: true,
          });
          comp.autoView();
        });

      const handleResize = () => stage.handleResize();
      window.addEventListener("resize", handleResize);

      return () => {
        window.removeEventListener("resize", handleResize);
      };
    });

    return () => {
      cancelled = true;
      if (stageRef.current) {
        (stageRef.current as { dispose(): void }).dispose();
        stageRef.current = null;
      }
    };
  }, [pdbText]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full rounded-xl overflow-hidden"
      style={{ minHeight: 320 }}
    />
  );
}
