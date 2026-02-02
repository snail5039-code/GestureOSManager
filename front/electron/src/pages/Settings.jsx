import GestureSettingsPanel from "../components/GestureSettingsPanel";

export default function Settings({ theme }) {
  return <GestureSettingsPanel theme={theme} embedded={false} />;
}
