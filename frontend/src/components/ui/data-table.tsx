import * as React from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { languageLocale } from "@/lib/i18n"
import { cn } from "@/lib/utils"

export type DataTableColumn<T> = {
  key: string
  header: string
  cell: (row: T) => React.ReactNode
  sortValue?: (row: T) => string | number | null | undefined
  className?: string
}

type DataTableProps<T> = {
  rows: T[]
  columns: DataTableColumn<T>[]
  getSearchText: (row: T) => string
  getRowKey: (row: T) => string | number
  pageSize?: number
  minWidthClassName?: string
  emptyState: React.ReactNode
  filterPlaceholder?: string
  mobileCard?: (row: T) => React.ReactNode
}

export function DataTable<T>({ rows, columns, getSearchText, getRowKey, pageSize = 8, minWidthClassName = "min-w-[720px]", emptyState, filterPlaceholder = "Filter", mobileCard }: DataTableProps<T>) {
  const [filter, setFilter] = React.useState("")
  const [sortKey, setSortKey] = React.useState(columns.find((column) => column.sortValue)?.key || columns[0]?.key || "")
  const [sortDirection, setSortDirection] = React.useState<"asc" | "desc">("desc")
  const [page, setPage] = React.useState(0)
  const normalizedFilter = filter.trim().toLowerCase()
  const sortColumn = columns.find((column) => column.key === sortKey)
  const sortableColumns = columns.filter((column) => column.sortValue)

  const filteredRows = React.useMemo(() => {
    const visible = normalizedFilter ? rows.filter((row) => getSearchText(row).toLowerCase().includes(normalizedFilter)) : [...rows]
    if (sortColumn?.sortValue) {
      visible.sort((left, right) => {
        const leftValue = sortColumn.sortValue?.(left)
        const rightValue = sortColumn.sortValue?.(right)
        if (leftValue === rightValue) return 0
        if (leftValue === null || leftValue === undefined) return 1
        if (rightValue === null || rightValue === undefined) return -1
        const result = typeof leftValue === "number" && typeof rightValue === "number" ? leftValue - rightValue : String(leftValue).localeCompare(String(rightValue))
        return sortDirection === "asc" ? result : -result
      })
    }
    return visible
  }, [getSearchText, normalizedFilter, rows, sortColumn, sortDirection])

  React.useEffect(() => { setPage(0) }, [normalizedFilter, sortKey, sortDirection])

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize))
  const currentPage = Math.min(page, pageCount - 1)
  const pageRows = filteredRows.slice(currentPage * pageSize, currentPage * pageSize + pageSize)
  const english = languageLocale() === "en-US"
  const labels = english
    ? { sort: "Sort cards", asc: "ascending", desc: "descending", rows: "rows", page: "Page", prev: "Prev", next: "Next" }
    : { sort: "Сортировка карточек", asc: "по возр.", desc: "по убыв.", rows: "строк", page: "Страница", prev: "Назад", next: "Вперед" }

  function toggleSort(column: DataTableColumn<T>) {
    if (!column.sortValue) return
    if (sortKey === column.key) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc")
      return
    }
    setSortKey(column.key)
    setSortDirection("desc")
  }

  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 text-xs">
      <Input className="w-full sm:max-w-xs" value={filter} placeholder={filterPlaceholder} onChange={(event) => setFilter(event.target.value)} />
      {mobileCard && sortableColumns.length ? <div className="flex w-full items-center gap-2 md:hidden">
        <Select aria-label={labels.sort} value={sortKey} onChange={(event) => { setSortKey(event.target.value); setSortDirection("desc") }}>
          {sortableColumns.map((column) => <option key={column.key} value={column.key}>{column.header}</option>)}
        </Select>
        <Button type="button" size="sm" variant="secondary" onClick={() => setSortDirection((current) => current === "asc" ? "desc" : "asc")}>{sortDirection === "asc" ? labels.asc : labels.desc}</Button>
      </div> : null}
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{filteredRows.length} {labels.rows}</span>
    </div>
    {mobileCard ? <div className="grid gap-2 px-4 md:hidden">
      {pageRows.map((row) => <React.Fragment key={getRowKey(row)}>{mobileCard(row)}</React.Fragment>)}
      {!pageRows.length ? <div className="text-xs text-zinc-500">{emptyState}</div> : null}
    </div> : null}
    <div className={cn("overflow-x-auto", mobileCard && "hidden md:block")}>
      <table className={cn("w-full text-left text-xs", minWidthClassName)}>
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr>{columns.map((column) => <th key={column.key} className={cn("px-4 py-2", column.className)}>{column.sortValue ? <button type="button" className="inline-flex items-center gap-1 text-left hover:text-zinc-200" onClick={() => toggleSort(column)}>{column.header}{sortKey === column.key ? <span>{sortDirection}</span> : null}</button> : column.header}</th>)}</tr></thead>
        <tbody>{pageRows.map((row) => <tr key={getRowKey(row)} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60">{columns.map((column) => <td key={column.key} className={cn("px-4 py-3", column.className)}>{column.cell(row)}</td>)}</tr>)}</tbody>
      </table>
      {!pageRows.length ? <div className="p-4 text-xs text-zinc-500">{emptyState}</div> : null}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-4 text-xs text-zinc-500">
      <span>{labels.page} {currentPage + 1} / {pageCount}</span>
      <div className="flex gap-2"><Button type="button" size="sm" variant="secondary" disabled={currentPage <= 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>{labels.prev}</Button><Button type="button" size="sm" variant="secondary" disabled={currentPage >= pageCount - 1} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>{labels.next}</Button></div>
    </div>
  </div>
}
