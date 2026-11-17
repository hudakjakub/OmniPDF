using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Printing;
using Windows.Graphics.Printing;
using Windows.Graphics.Printing.OptionDetails;
using Windows.Storage;
using WinRT.Interop;

namespace OmniPrint;

public partial class App : Application
{
    private Window window;
    private Canvas root;
    private PrintDocument document;
    private IPrintDocumentSource source;
    private PrintManager manager;
    private string[] pages;
    private string title;
    private PrintPageDescription description;
    private int generation;
    private readonly TaskCompletionSource<PrintTaskCompletion> completion = new();

    public App() { InitializeComponent(); }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        int exitCode = 2;
        try
        {
            string[] arguments = Environment.GetCommandLineArgs();
            if (arguments.Length == 2 && arguments[1] == "--check") { exitCode = 0; return; }
            if (arguments.Length != 3) throw new ArgumentException();
            pages = Directory.GetFiles(arguments[1], "*.png");
            Array.Sort(pages, StringComparer.Ordinal);
            if (pages.Length == 0) throw new ArgumentException();
            title = arguments[2];
            window = new Window { Title = "Omni PDF" };
            window.AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(-32000, -32000, 1, 1));
            root = new Canvas();
            window.Content = root;
            window.Activate();
            IntPtr hwnd = WindowNative.GetWindowHandle(window);
            document = new PrintDocument();
            source = document.DocumentSource;
            document.Paginate += Paginate;
            document.GetPreviewPage += GetPreviewPage;
            document.AddPages += AddPages;
            manager = PrintManagerInterop.GetForWindow(hwnd);
            manager.PrintTaskRequested += PrintTaskRequested;
            if (!await PrintManagerInterop.ShowPrintUIForWindowAsync(hwnd)) throw new InvalidOperationException();
            PrintTaskCompletion result = await completion.Task;
            exitCode = result == PrintTaskCompletion.Submitted ? 0 :
                result == PrintTaskCompletion.Canceled || result == PrintTaskCompletion.Abandoned ? 1 : 2;
        }
        catch (Exception) { exitCode = 2; }
        finally
        {
            if (manager != null) manager.PrintTaskRequested -= PrintTaskRequested;
            window?.Close();
            Environment.ExitCode = exitCode;
            Exit();
        }
    }

    private void PrintTaskRequested(PrintManager sender, PrintTaskRequestedEventArgs args)
    {
        PrintTask task = null;
        task = args.Request.CreatePrintTask(title, requested =>
        {
            try
            {
                var options = PrintTaskOptionDetails.GetFromPrintTaskOptions(task.Options);
                if (!options.DisplayedOptions.Contains(StandardPrintTaskOptions.CustomPageRanges))
                    options.DisplayedOptions.Add(StandardPrintTaskOptions.CustomPageRanges);
                task.Options.PageRangeOptions.AllowCurrentPage = true;
                task.Options.PageRangeOptions.AllowAllPages = true;
                task.Options.PageRangeOptions.AllowCustomSetOfPages = true;
                requested.SetSource(source);
            }
            catch (Exception error) { completion.TrySetException(error); }
        });
        task.Completed += (sender, args) => completion.TrySetResult(args.Completion);
    }

    private void Paginate(object sender, PaginateEventArgs args)
    {
        try
        {
            generation++;
            description = args.PrintTaskOptions.GetPageDescription(0);
            root.Children.Clear();
            document.SetPreviewPageCount(pages.Length, PreviewPageCountType.Final);
        }
        catch (Exception error) { completion.TrySetException(error); }
    }

    private async Task<UIElement> CreatePage(int index, PrintPageDescription pageDescription)
    {
        var bitmap = new BitmapImage();
        var file = await StorageFile.GetFileFromPathAsync(pages[index]);
        using (var stream = await file.OpenReadAsync()) await bitmap.SetSourceAsync(stream);
        var page = new Canvas { Width = pageDescription.PageSize.Width, Height = pageDescription.PageSize.Height };
        var area = pageDescription.ImageableRect;
        var image = new Image { Source = bitmap, Stretch = Stretch.Uniform, Width = area.Width, Height = area.Height };
        Canvas.SetLeft(image, area.X);
        Canvas.SetTop(image, area.Y);
        page.Children.Add(image);
        root.Children.Add(page);
        page.UpdateLayout();
        return page;
    }

    private async void GetPreviewPage(object sender, GetPreviewPageEventArgs args)
    {
        try
        {
            int currentGeneration = generation;
            UIElement page = await CreatePage(args.PageNumber - 1, description);
            if (currentGeneration == generation) document.SetPreviewPage(args.PageNumber, page);
            else root.Children.Remove(page);
        }
        catch (Exception error) { completion.TrySetException(error); }
    }

    private async void AddPages(object sender, AddPagesEventArgs args)
    {
        try
        {
            var ranges = args.PrintTaskOptions.CustomPageRanges;
            if (ranges.Count == 0)
            {
                for (int i = 0; i < pages.Length; i++) document.AddPage(await CreatePage(i, description));
            }
            else
            {
                foreach (var range in ranges)
                    for (int i = Math.Max(1, range.FirstPageNumber); i <= range.LastPageNumber && i <= pages.Length; i++)
                        document.AddPage(await CreatePage(i - 1, description));
            }
            document.AddPagesComplete();
        }
        catch (Exception error) { completion.TrySetException(error); }
    }
}
