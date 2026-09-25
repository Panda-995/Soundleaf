import React, { useEffect, useRef, useState } from "react";
import * as Menu from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

type Props = Omit<
  React.SelectHTMLAttributes<HTMLSelectElement>,
  "multiple" | "size"
>;
export function Select({
  children,
  value,
  defaultValue,
  onChange,
  disabled,
  required,
  name,
  id,
  className,
  ...aria
}: Props) {
  const trigger = useRef<HTMLButtonElement>(null);
  // Refs are null on first render, so the portal container is resolved after
  // mount; otherwise a Select inside a native <dialog> would always portal to
  // <body> and its menu would be trapped under the top layer.
  const [container, setContainer] = useState<HTMLElement | undefined>(
    undefined,
  );
  useEffect(() => {
    setContainer(trigger.current?.closest("dialog") || undefined);
  }, []);
  const empty = "__soundleaf_empty__";
  const options = React.Children.toArray(children).filter(
    React.isValidElement,
  ) as React.ReactElement<{
    value?: string | number;
    disabled?: boolean;
    children: React.ReactNode;
  }>[];
  const actual = String(value ?? defaultValue ?? options[0]?.props.value ?? "");
  const selected = options.some(
    (o) => String(o.props.value ?? o.props.children) === actual,
  );
  return (
    <Menu.Root
      value={actual || empty}
      onValueChange={(v) =>
        onChange?.({
          target: { value: v === empty ? "" : v },
          currentTarget: { value: v === empty ? "" : v },
        } as React.ChangeEvent<HTMLSelectElement>)
      }
      disabled={disabled}
      required={required}
      name={name}
    >
      <Menu.Trigger
        ref={trigger}
        id={id}
        className={"select-trigger " + (className || "")}
        aria-label={aria["aria-label"]}
        aria-labelledby={aria["aria-labelledby"]}
        aria-describedby={aria["aria-describedby"]}
        aria-invalid={aria["aria-invalid"]}
        title={aria.title}
      >
        <Menu.Value />
        <Menu.Icon className="select-chevron">
          <ChevronDown size={16} />
        </Menu.Icon>
      </Menu.Trigger>
      <Menu.Portal container={container}>
        <Menu.Content
          className="select-menu"
          position="popper"
          sideOffset={6}
          collisionPadding={12}
        >
          <Menu.ScrollUpButton className="select-scroll">
            <ChevronUp size={15} />
          </Menu.ScrollUpButton>
          <Menu.Viewport className="select-options">
            {!selected && (
              <Menu.Item value={actual || empty} className="select-option">
                <Menu.ItemText>{actual || "请选择"}</Menu.ItemText>
              </Menu.Item>
            )}
            {options.map((o, i) => (
              <Menu.Item
                value={String(o.props.value ?? o.props.children) || empty}
                key={i}
                className="select-option"
                disabled={o.props.disabled}
              >
                <Menu.ItemText>{o.props.children}</Menu.ItemText>
                <Menu.ItemIndicator className="select-check">
                  <Check size={15} />
                </Menu.ItemIndicator>
              </Menu.Item>
            ))}
          </Menu.Viewport>
          <Menu.ScrollDownButton className="select-scroll">
            <ChevronDown size={15} />
          </Menu.ScrollDownButton>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
