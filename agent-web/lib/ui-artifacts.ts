import { z } from "zod";

const tableCellSchema = z.union([z.string(), z.number()]);

export type WidgetComponentNode =
  | {
      name: "card";
      children: WidgetComponentNode[];
    }
  | {
      name: "header";
      content: string;
    }
  | {
      name: "table";
      columns: Array<{ key: string; title: string }>;
      rows: Array<{ values: Array<string | number> }>;
    }
  | {
      name: "bar_chart";
      columns: Array<{ label: string; value: number }>;
    }
  | {
      name: "item_card";
      title: string;
      description?: string;
      eyebrow?: string;
      price?: string;
      image_url?: string;
      cta_label?: string;
    };

export const widgetComponentSchema: z.ZodType<WidgetComponentNode> = z.lazy(() =>
  z.union([
    z.object({
      name: z.literal("card"),
      children: z.array(widgetComponentSchema).max(12),
    }),
    z.object({
      name: z.literal("header"),
      content: z.string().min(1).max(240),
    }),
    z.object({
      name: z.literal("table"),
      columns: z
        .array(
          z.object({
            key: z.string().min(1).max(80),
            title: z.string().min(1).max(120),
          }),
        )
        .min(1)
        .max(8),
      rows: z
        .array(
          z.object({
            values: z.array(tableCellSchema).min(1).max(8),
          }),
        )
        .max(24),
    }),
    z.object({
      name: z.literal("bar_chart"),
      columns: z
        .array(
          z.object({
            label: z.string().min(1).max(80),
            value: z.number().finite(),
          }),
        )
        .min(1)
        .max(12),
    }),
    z.object({
      name: z.literal("item_card"),
      title: z.string().min(1).max(160),
      description: z.string().max(600).optional(),
      eyebrow: z.string().max(80).optional(),
      price: z.string().max(40).optional(),
      image_url: z.string().url().optional(),
      cta_label: z.string().max(40).optional(),
    }),
  ]),
);

export const componentTreeArtifactSchema = z.object({
  type: z.literal("component_tree"),
  version: z.literal("v1"),
  payload: z.object({
    root: widgetComponentSchema,
  }),
});

export type ComponentTreeArtifact = z.infer<typeof componentTreeArtifactSchema>;

export function parseComponentTreeArtifact(artifact: unknown) {
  return componentTreeArtifactSchema.safeParse(artifact);
}
