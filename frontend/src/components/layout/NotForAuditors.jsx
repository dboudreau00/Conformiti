import { useNavigate } from "react-router-dom";
import { Button } from "../ui/Button.jsx";
import { Empty, Panel } from "../ui/Panel.jsx";
import { PanelTransition } from "./PanelTransition.jsx";

export function NotForAuditors() {
  const nav = useNavigate();
  return (
    <PanelTransition>
      <Panel>
        <Empty
          title="Not available to an auditor account"
          action={<Button size="sm" variant="primary" onClick={() => nav("/packages")}>Go to your packages</Button>}
        />
      </Panel>
    </PanelTransition>
  );
}
