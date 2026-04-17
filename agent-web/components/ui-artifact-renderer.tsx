"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ComponentTreeArtifact, WidgetComponentNode } from "@/lib/ui-artifacts";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from "recharts";

function HeaderComponent({ content }: { content: string }) {
  return <h3 className="text-lg font-semibold tracking-tight text-foreground">{content}</h3>;
}

function CardComponent({ children }: { children: WidgetComponentNode[] }) {
  return (
    <div className="rounded-[1.25rem] border border-border bg-white px-4 py-4 shadow-sm">
      <div className="space-y-4">
        {children.map((child, index) => (
          <UiComponentNode key={`${child.name}-${index}`} component={child} />
        ))}
      </div>
    </div>
  );
}

function TableComponent({
  columns,
  rows,
}: Extract<WidgetComponentNode, { name: "table" }>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHead key={column.key}>{column.title}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, rowIndex) => (
          <TableRow key={rowIndex}>
            {row.values.map((value, cellIndex) => (
              <TableCell key={`${rowIndex}-${cellIndex}`}>{value}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BarChartComponent({
  columns,
}: Extract<WidgetComponentNode, { name: "bar_chart" }>) {
  return (
    <div className="h-64 w-full rounded-[1.1rem] border border-border bg-slate-950/95 p-3 text-white">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={columns}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.12)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "rgba(255,255,255,0.72)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "rgba(255,255,255,0.72)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <Bar dataKey="value" fill="#4dd0c8" radius={[8, 8, 0, 0]} barSize={34} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ItemCardComponent({
  title,
  description,
  eyebrow,
  price,
  image_url,
  cta_label,
}: Extract<WidgetComponentNode, { name: "item_card" }>) {
  return (
    <div className="overflow-hidden rounded-[1.25rem] border border-border bg-white shadow-sm">
      {image_url ? (
        // Native img is sufficient here because URLs are data-only and never executable.
        <img
          src={image_url}
          alt={title}
          className="h-40 w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="h-40 w-full bg-[linear-gradient(135deg,rgba(16,132,120,0.18),rgba(7,93,105,0.34))]" />
      )}
      <div className="space-y-3 px-4 py-4">
        {eyebrow ? (
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <div className="space-y-1">
          <h4 className="text-base font-semibold text-foreground">{title}</h4>
          {description ? <p className="text-sm leading-6 text-muted-foreground">{description}</p> : null}
        </div>
        <div className="flex items-center justify-between gap-4 pt-1">
          <span className="text-sm font-semibold text-foreground">{price || ""}</span>
          {cta_label ? (
            <span className="rounded-full bg-accent px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] text-accent-foreground">
              {cta_label}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function UiComponentNode({ component }: { component: WidgetComponentNode }) {
  switch (component.name) {
    case "card":
      return <CardComponent children={component.children} />;
    case "header":
      return <HeaderComponent content={component.content} />;
    case "table":
      return <TableComponent {...component} />;
    case "bar_chart":
      return <BarChartComponent {...component} />;
    case "item_card":
      return <ItemCardComponent {...component} />;
    default:
      return null;
  }
}

export default function UiArtifactRenderer({
  artifact,
}: {
  artifact: ComponentTreeArtifact;
}) {
  return <UiComponentNode component={artifact.payload.root} />;
}
