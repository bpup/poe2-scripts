using System.Runtime.InteropServices;
using ExileCore2;

namespace AutoFollow.Core;

/// <summary>
/// Background-compatible input injection via PostMessage.
/// 
/// CRITICAL DIFFERENCE from frame-based input:
/// - SendInput/SetCursorPos REQUIRES the window to be in foreground.
///   PoE2 uses DirectInput which ignores virtual key states from PostMessage,
///   BUT mouse clicks (WM_LBUTTONDOWN/UP) are processed through the standard
///   Windows message queue and work on background windows.
/// 
/// - Mouse movement via PostMessage does NOT work reliably (game reads raw
///   cursor position). Instead, we use PostMessage to send click events at
///   a SCREEN coordinate. The game maps screen→world and auto-paths.
/// 
/// - Keyboard keys (skills, flasks) are sent as WM_KEYDOWN/UP.
///   These work for skills but NOT for WASD movement (DirectInput).
/// </summary>
public static class BackgroundInput
{
    private const uint WM_LBUTTONDOWN = 0x0201;
    private const uint WM_LBUTTONUP   = 0x0202;
    private const uint WM_KEYDOWN     = 0x0100;
    private const uint WM_KEYUP       = 0x0101;

    // -- Native imports --------------------------------------------------

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    private static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left, Top, Right, Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X, Y;
    }

    // -- Public API ------------------------------------------------------

    /// <summary>
    /// Click on a screen coordinate in a BACKGROUND window.
    /// Uses PostMessage → works without foreground focus.
    /// </summary>
    public static void ClickAt(IntPtr hwnd, int screenX, int screenY)
    {
        IntPtr lParam = (IntPtr)((screenY << 16) | (screenX & 0xFFFF));
        PostMessage(hwnd, WM_LBUTTONDOWN, IntPtr.Zero, lParam);
        PostMessage(hwnd, WM_LBUTTONUP,   IntPtr.Zero, lParam);
    }

    /// <summary>
    /// Click at a world position. Converts world → screen → PostMessage click.
    /// The game's built-in pathfinding handles the navigation.
    /// </summary>
    public static bool ClickWorldPos(IntPtr hwnd, SharpDX.Vector2 worldPos, GameController gameController)
    {
        try
        {
            var ingameState = gameController?.IngameState;
            if (ingameState?.Data == null) return false;

            // Use the game's Camera to convert world → screen
            var camera = gameController.Game.IngameState.Camera;
            if (camera == null) return false;

            var screenVec = camera.WorldToScreen(worldPos);
            if (screenVec == SharpDX.Vector2.Zero) return false;

            // Convert to screen coordinates relative to the window
            var window = ingameState.IngameUi.GameWindowRect;
            int clickX = (int)(screenVec.X + window.X);
            int clickY = (int)(screenVec.Y + window.Y);

            // Clamp to window bounds
            if (clickX < window.X || clickX > window.X + window.Width ||
                clickY < window.Y || clickY > window.Y + window.Height)
                return false;

            clickY = Math.Clamp(clickY, window.Y, window.Y + window.Height);
            clickX = Math.Clamp(clickX, window.X, window.X + window.Width);

            ClickAt(hwnd, clickX, clickY);
            return true;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Send a keyboard key to a background window.
    /// Works for skill/item hotkeys (Q/W/E/R/T, 1-5, etc.)
    /// Does NOT work for WASD movement (game uses DirectInput).
    /// </summary>
    public static void SendKey(IntPtr hwnd, System.Windows.Forms.Keys key)
    {
        PostMessage(hwnd, WM_KEYDOWN, (IntPtr)key, IntPtr.Zero);
        PostMessage(hwnd, WM_KEYUP,   (IntPtr)key, IntPtr.Zero);
    }
}
