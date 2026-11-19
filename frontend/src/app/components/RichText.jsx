import { useEffect } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Bold, Heading2, Italic, List, ListOrdered } from "lucide-react";

export const MERGE = [
  ["client.first_name", "Client first name"], ["client.name", "Client name"], ["client.company", "Client company"], ["project.name", "Project name"],
  ["project.value", "Project value"], ["practice.name", "Practice name"], ["consultant.name", "Your name"], ["today", "Today"],
  ["services.recap", "Services chosen"], ["payments.recap", "Payment schedule"], ["session.date", "Session date"], ["session.time", "Session time"],
  ["session.link", "Session link"], ["booking.link", "Booking link"], ["file.link", "File link"], ["portal.link", "Portal link"],
];

/** Rich text with merge fields (TipTap). */
export default function RichText({ value, onChange, placeholder = "Write here…", fields = [] }) {
  const ed = useEditor({
    extensions: [StarterKit],
    content: value || "",
    editorProps: { attributes: { class: "prose-dark min-h-[120px] rounded-input border border-hairline bg-panel px-3.5 py-3 text-[15px] focus:border-gold", "data-placeholder": placeholder } },
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  });
  useEffect(() => {
    if (ed && value !== ed.getHTML() && !ed.isFocused) ed.commands.setContent(value || "", false);
  }, [value, ed]);
  if (!ed) return null;
  const B = ({ on, act, children, label }) => (
    <button type="button" aria-label={label} onClick={act} className={`grid h-9 w-9 place-items-center rounded-lg ${on ? "bg-gold/20 text-gold" : "text-ivory-70 hover:bg-panel-raised"}`}>{children}</button>
  );
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-1">
        <B label="Bold" on={ed.isActive("bold")} act={() => ed.chain().focus().toggleBold().run()}><Bold size={15} /></B>
        <B label="Italic" on={ed.isActive("italic")} act={() => ed.chain().focus().toggleItalic().run()}><Italic size={15} /></B>
        <B label="Heading" on={ed.isActive("heading", { level: 2 })} act={() => ed.chain().focus().toggleHeading({ level: 2 }).run()}><Heading2 size={15} /></B>
        <B label="List" on={ed.isActive("bulletList")} act={() => ed.chain().focus().toggleBulletList().run()}><List size={15} /></B>
        <B label="Numbered list" on={ed.isActive("orderedList")} act={() => ed.chain().focus().toggleOrderedList().run()}><ListOrdered size={15} /></B>
        <select className="ml-auto h-9 rounded-lg border border-hairline bg-panel px-2 text-[13px]" value="" onChange={(e) => { e.target.value && ed.chain().focus().insertContent(`{{${e.target.value}}}`).run(); }}>
          <option value="">Insert field…</option>
          {MERGE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          {fields.map((f) => <option key={f.key} value={`field:${f.key}`}>Contract field: {f.label}</option>)}
        </select>
      </div>
      <EditorContent editor={ed} />
    </div>
  );
}
