import { useNavigate } from "react-router-dom";
import { Button } from "../ui/Button.jsx";
import { Empty, Panel } from "../ui/Panel.jsx";
import { PanelTransition } from "./PanelTransition.jsx";

/** What an external auditor sees at an address the menu never offers them: a
 *  typed path or an old bookmark. The API refuses the request either way, so
 *  this says so once, rather than letting the page's own load fail twice over
 *  under a Try again that cannot succeed. */
export function NotForAuditors() {
  const nav = useNavigate();
  return (
    <PanelTransition>
      <Panel>
        <Empty
          title="Not available to an auditor account"
          action={<Button size="sm" variant="primary" onClick={() => nav("/packages")}>Go to your packages</Button>}
        >
          This account opens the evidence packages issued to it, the folders granted with them, the access reviews and the audit log. The rest of the workspace is for the organisation's own people.
        </Empty>
      </Panel>
    </PanelTransition>
  );
}
