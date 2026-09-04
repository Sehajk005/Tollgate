import { useCallback, useState } from "react";

import S1Product from "./screens/S1Product.jsx";
import S2Checkout from "./screens/S2Checkout.jsx";
import S3Challenge from "./screens/S3Challenge.jsx";
import S5Confirmed from "./screens/S5Confirmed.jsx";
import S6Blocked from "./screens/S6Blocked.jsx";
import S7Throttle from "./screens/S7Throttle.jsx";

// Day 8, Step 8 -- the storefront shell + screen state machine. No router
// (App Flow SS2): S1 -> S2 -> {S5 | S3 | S6 | S7}; S3 passed -> S5, failed ->
// S6; S7 returns to S2. S4 (3DS step-up) is NOT built -- it is unreachable
// without a confirmed step_up (App Flow cut candidate #2).
//
// Kesar & Co.: light polarity, airy density, deep-green accent, a system font
// stack. Styled as if built by a different company from the dashboard
// (UIUX v2 SS1).

const DEMO = new URLSearchParams(window.location.search).get("demo") === "1";

export default function App() {
  const [screen, setScreen] = useState("S1");

  const route = useCallback((screenId) => {
    // S4 is not built; the auto-ceiling makes it unreachable anyway. Fall back
    // to S5 defensively rather than dead-end.
    setScreen(screenId === "S4" ? "S5" : screenId);
  }, []);

  return (
    <div className="st-app">
      {screen === "S1" && <S1Product onBuy={() => setScreen("S2")} />}
      {screen === "S2" && <S2Checkout demo={DEMO} onRoute={route} />}
      {screen === "S3" && (
        <S3Challenge onPass={() => setScreen("S5")} onFail={() => setScreen("S6")} />
      )}
      {screen === "S5" && <S5Confirmed onDone={() => setScreen("S1")} />}
      {screen === "S6" && <S6Blocked onRetry={() => setScreen("S1")} />}
      {screen === "S7" && <S7Throttle onReturn={() => setScreen("S2")} />}
    </div>
  );
}
