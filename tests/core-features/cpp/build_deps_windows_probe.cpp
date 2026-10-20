/*
 * Copyright (C) Ascensio System SIA, 2009-2026
 * SPDX-License-Identifier: AGPL-3.0-only
 */

#include <ft2build.h>
#include FT_FREETYPE_H
#include <hb.h>
#include <hb-ft.h>
#include <openjpeg.h>
#include <png.h>

#include <csetjmp>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

struct PngBytes
{
	std::vector<unsigned char> value;
	size_t offset = 0;
};

static void pngFailure(png_structp png, png_const_charp message)
{
	std::fprintf(stderr, "PNG error: %s\n", message ? message : "unknown");
	longjmp(png_jmpbuf(png), 1);
}

static void pngWarning(png_structp, png_const_charp message)
{
	std::fprintf(stderr, "PNG warning: %s\n", message ? message : "unknown");
}

static void pngWrite(png_structp png, png_bytep data, png_size_t size)
{
	auto* bytes = static_cast<PngBytes*>(png_get_io_ptr(png));
	bytes->value.insert(bytes->value.end(), data, data + size);
}

static void pngFlush(png_structp) {}

static void pngRead(png_structp png, png_bytep data, png_size_t size)
{
	auto* bytes = static_cast<PngBytes*>(png_get_io_ptr(png));
	if (bytes->offset + size > bytes->value.size())
		png_error(png, "unexpected end of PNG buffer");
	std::memcpy(data, bytes->value.data() + bytes->offset, size);
	bytes->offset += size;
}

static bool probePng()
{
	const unsigned char expected[] = {
		255, 0, 0, 255, 0, 255, 0, 255,
		0, 0, 255, 255, 255, 255, 255, 255
	};
	PngBytes encoded;
	png_structp writer = png_create_write_struct(PNG_LIBPNG_VER_STRING, nullptr, pngFailure, pngWarning);
	if (!writer)
		return false;
	png_infop writerInfo = png_create_info_struct(writer);
	if (!writerInfo)
	{
		png_destroy_write_struct(&writer, nullptr);
		return false;
	}
	if (setjmp(png_jmpbuf(writer)))
	{
		png_destroy_write_struct(&writer, &writerInfo);
		return false;
	}
	png_set_write_fn(writer, &encoded, pngWrite, pngFlush);
	png_set_IHDR(writer, writerInfo, 2, 2, 8, PNG_COLOR_TYPE_RGBA,
		PNG_INTERLACE_NONE, PNG_COMPRESSION_TYPE_DEFAULT, PNG_FILTER_TYPE_DEFAULT);
	png_write_info(writer, writerInfo);
	png_bytep rows[] = {const_cast<png_bytep>(expected), const_cast<png_bytep>(expected + 8)};
	png_write_image(writer, rows);
	png_write_end(writer, writerInfo);
	png_destroy_write_struct(&writer, &writerInfo);
	if (encoded.value.empty())
		return false;

	png_structp reader = png_create_read_struct(PNG_LIBPNG_VER_STRING, nullptr, pngFailure, pngWarning);
	if (!reader)
		return false;
	png_infop readerInfo = png_create_info_struct(reader);
	if (!readerInfo)
	{
		png_destroy_read_struct(&reader, nullptr, nullptr);
		return false;
	}
	if (setjmp(png_jmpbuf(reader)))
	{
		png_destroy_read_struct(&reader, &readerInfo, nullptr);
		return false;
	}
	png_set_read_fn(reader, &encoded, pngRead);
	png_read_info(reader, readerInfo);
	if (png_get_image_width(reader, readerInfo) != 2 || png_get_image_height(reader, readerInfo) != 2)
	{
		png_destroy_read_struct(&reader, &readerInfo, nullptr);
		return false;
	}
	std::vector<unsigned char> decoded(sizeof(expected));
	png_bytep decodedRows[] = {decoded.data(), decoded.data() + 8};
	png_read_image(reader, decodedRows);
	png_read_end(reader, readerInfo);
	png_destroy_read_struct(&reader, &readerInfo, nullptr);
	return std::memcmp(decoded.data(), expected, sizeof(expected)) == 0;
}

static void opjMessage(const char* message, void*)
{
	if (message)
		std::fprintf(stderr, "%s", message);
}

static bool probeOpenJpeg(const char* outputPath)
{
	opj_image_cmptparm_t components[3] = {};
	for (auto& component : components)
	{
		component.dx = 1;
		component.dy = 1;
		component.w = 2;
		component.h = 2;
		component.prec = 8;
		component.bpp = 8;
	}
	opj_image_t* source = opj_image_create(3, components, OPJ_CLRSPC_SRGB);
	if (!source)
		return false;
	source->x1 = 2;
	source->y1 = 2;
	const OPJ_INT32 pixels[3][4] = {{255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}};
	for (int c = 0; c < 3; ++c)
		for (int i = 0; i < 4; ++i)
			source->comps[c].data[i] = pixels[c][i];

	opj_cparameters_t encodeParameters;
	opj_set_default_encoder_parameters(&encodeParameters);
	encodeParameters.tcp_numlayers = 1;
	encodeParameters.numresolution = 1;
	encodeParameters.tcp_rates[0] = 0;
	encodeParameters.cp_disto_alloc = 1;
	encodeParameters.tcp_mct = 1;
	opj_codec_t* encoder = opj_create_compress(OPJ_CODEC_JP2);
	if (!encoder)
	{
		opj_image_destroy(source);
		return false;
	}
	opj_set_error_handler(encoder, opjMessage, nullptr);
	if (!opj_setup_encoder(encoder, &encodeParameters, source))
	{
		opj_destroy_codec(encoder);
		opj_image_destroy(source);
		return false;
	}
	opj_stream_t* output = opj_stream_create_default_file_stream(outputPath, OPJ_FALSE);
	bool encoded = output && opj_start_compress(encoder, source, output)
		&& opj_encode(encoder, output) && opj_end_compress(encoder, output);
	if (output)
		opj_stream_destroy(output);
	opj_destroy_codec(encoder);
	opj_image_destroy(source);
	if (!encoded)
		return false;

	opj_dparameters_t decodeParameters;
	opj_set_default_decoder_parameters(&decodeParameters);
	opj_codec_t* decoder = opj_create_decompress(OPJ_CODEC_JP2);
	if (!decoder)
		return false;
	opj_set_error_handler(decoder, opjMessage, nullptr);
	if (!opj_setup_decoder(decoder, &decodeParameters))
	{
		opj_destroy_codec(decoder);
		return false;
	}
	opj_stream_t* input = opj_stream_create_default_file_stream(outputPath, OPJ_TRUE);
	opj_image_t* decoded = nullptr;
	bool ok = input && opj_read_header(input, decoder, &decoded) && decoded
		&& opj_decode(decoder, input, decoded) && opj_end_decompress(decoder, input)
		&& decoded->x1 - decoded->x0 == 2 && decoded->y1 - decoded->y0 == 2
		&& decoded->numcomps == 3;
	if (input)
		opj_stream_destroy(input);
	if (decoded)
		opj_image_destroy(decoded);
	opj_destroy_codec(decoder);
	return ok;
}

static bool probeTextShaping(const char* fontPath, unsigned int& glyphCount)
{
	FT_Library library = nullptr;
	if (FT_Init_FreeType(&library) != 0)
		return false;
	FT_Face face = nullptr;
	if (FT_New_Face(library, fontPath, 0, &face) != 0)
	{
		FT_Done_FreeType(library);
		return false;
	}
	hb_font_t* font = hb_ft_font_create_referenced(face);
	hb_buffer_t* buffer = hb_buffer_create();
	if (!font || !buffer)
	{
		if (buffer) hb_buffer_destroy(buffer);
		if (font) hb_font_destroy(font);
		FT_Done_Face(face);
		FT_Done_FreeType(library);
		return false;
	}
	const char text[] = "Office";
	hb_buffer_add_utf8(buffer, text, -1, 0, -1);
	hb_buffer_guess_segment_properties(buffer);
	hb_shape(font, buffer, nullptr, 0);
	unsigned int count = 0;
	hb_glyph_info_t* glyphs = hb_buffer_get_glyph_infos(buffer, &count);
	bool ok = count >= 4 && glyphs != nullptr;
	for (unsigned int i = 0; ok && i < count; ++i)
		ok = glyphs[i].codepoint != 0;
	glyphCount = count;
	hb_buffer_destroy(buffer);
	hb_font_destroy(font);
	FT_Done_Face(face);
	FT_Done_FreeType(library);
	return ok;
}

int main(int argc, char** argv)
{
	if (argc != 3)
	{
		std::fprintf(stderr, "usage: build_deps_windows_probe <font.ttf> <temporary.jp2>\n");
		return 2;
	}
	unsigned int glyphCount = 0;
	if (!probeTextShaping(argv[1], glyphCount))
	{
		std::fprintf(stderr, "FreeType/HarfBuzz text shaping probe failed\n");
		return 10;
	}
	std::printf("PASS freetype-harfbuzz-shaping glyphs=%u\n", glyphCount);
	if (!probePng())
	{
		std::fprintf(stderr, "Core PNG encode/decode probe failed\n");
		return 11;
	}
	std::puts("PASS png-encode-decode");
	if (!probeOpenJpeg(argv[2]))
	{
		std::fprintf(stderr, "OpenJPEG JP2 encode/decode probe failed\n");
		return 12;
	}
	std::puts("PASS openjpeg-jp2-encode-decode");
	return 0;
}
