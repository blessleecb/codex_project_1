import Foundation
import PDFKit

if CommandLine.arguments.count < 3 {
    fputs("usage: extract_pdf_text.swift <input.pdf> <output.txt>\n", stderr)
    exit(1)
}

let inputPath = CommandLine.arguments[1]
let outputPath = CommandLine.arguments[2]

guard let document = PDFDocument(url: URL(fileURLWithPath: inputPath)) else {
    fputs("failed to open pdf\n", stderr)
    exit(2)
}

var chunks: [String] = []
for index in 0..<document.pageCount {
    if let page = document.page(at: index), let text = page.string {
        chunks.append("=== PAGE \(index + 1) ===\n\(text)")
    }
}

let rendered = chunks.joined(separator: "\n\n")
try rendered.write(to: URL(fileURLWithPath: outputPath), atomically: true, encoding: .utf8)
print(outputPath)
