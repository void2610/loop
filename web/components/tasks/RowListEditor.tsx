"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// accept/constraints の ＋−行 UI(legacy todo_edit.html の rows/rowitem を踏襲)。
// 値の配列は親が状態管理する。空行は保存時に runner 側 _fm_from_form が落とす。
export function RowListEditor({
  rows,
  onChange,
  placeholder,
  addLabel = "＋ 項目を追加",
}: {
  rows: string[];
  onChange: (rows: string[]) => void;
  placeholder?: string;
  addLabel?: string;
}) {
  // 最低 1 行は表示する(legacy が末尾に空行を1つ足していた挙動)。
  const display = rows.length === 0 ? [""] : rows;

  function setAt(i: number, value: string) {
    const next = [...display];
    next[i] = value;
    onChange(next);
  }

  function removeAt(i: number) {
    if (display.length > 1) {
      onChange(display.filter((_, j) => j !== i));
    } else {
      onChange([""]);
    }
  }

  function add() {
    onChange([...display, ""]);
  }

  return (
    <div className="space-y-2">
      <div className="space-y-2">
        {display.map((value, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input
              value={value}
              placeholder={placeholder}
              onChange={(e) => setAt(i, e.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              title="削除"
              onClick={() => removeAt(i)}
            >
              −
            </Button>
          </div>
        ))}
      </div>
      <Button type="button" variant="ghost" size="sm" onClick={add}>
        {addLabel}
      </Button>
    </div>
  );
}
